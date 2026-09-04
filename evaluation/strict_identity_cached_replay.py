"""Hash-safe, resumable and bounded-parallel strict identity replay.

OCR-bearing cache records live below ``evaluation_data`` and must never be
committed. Page checkpoints and published reports contain no recognized text.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import psutil
from PIL import Image, ImageDraw

from evaluation.real_archive_classification import (
    Observation,
    PageRef,
    RapidOCRPageObserver,
    _safe_record,
    discover_pages,
)
from packages.document_routing import MultiSignalRoute, MultiSignalRouter
from packages.ocr import RapidOCRProvider
from workers.page_detection.text_extraction import TextLine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "evaluation_data/source_b_1000_claims"
DEFAULT_OUTPUT = ROOT / "evaluation_data/strict_identity_replay_v2"
DEFAULT_REPORT = ROOT / "evaluation_results/strict_identity_replay"
CACHE_KEY_VERSION = "strict-identity-ocr-cache-v1"
OCR_CONFIG_VERSION = "rapidocr-full-page-routing-v1"
PREPROCESSING_VERSION = "AUTO"
RUNNER_VERSION = "strict-identity-cached-replay-v1"
SUMMARY_INTERVAL = 25
_WORKER_OBSERVER: RapidOCRPageObserver | None = None


def _digest(value: bytes | str) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def rapidocr_version() -> str:
    try:
        return metadata.version("rapidocr-onnxruntime")
    except metadata.PackageNotFoundError:
        return "unknown"


def ocr_cache_key(page: PageRef, engine_version: str) -> str:
    payload = {
        "cache_key_version": CACHE_KEY_VERSION,
        "source_asset_sha256": page.asset_sha256,
        "frame_index": page.page_number - 1,
        "rendered_page_sha256": page.page_sha256,
        "ocr_engine": "rapidocr",
        "ocr_engine_version": engine_version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "ocr_config_version": OCR_CONFIG_VERSION,
    }
    return _digest(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _expected_provenance(page: PageRef, engine_version: str) -> dict[str, Any]:
    return {
        "source_asset_sha256": page.asset_sha256,
        "frame_index": page.page_number - 1,
        "rendered_page_sha256": page.page_sha256,
        "ocr_engine": "rapidocr",
        "ocr_engine_version": engine_version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "ocr_config_version": OCR_CONFIG_VERSION,
        "cache_key": ocr_cache_key(page, engine_version),
    }


def valid_cache_record(record: dict[str, Any], page: PageRef, engine_version: str) -> bool:
    expected = _expected_provenance(page, engine_version)
    if any(record.get(key) != value for key, value in expected.items()):
        return False
    if record.get("status") not in {"OCR_EXECUTED", "CACHE_HIT"}:
        return False
    tokens = record.get("tokens")
    return isinstance(tokens, list) and all(
        isinstance(token, dict)
        and isinstance(token.get("text"), str)
        and isinstance(token.get("bbox"), list)
        and len(token["bbox"]) == 4
        and isinstance(token.get("confidence"), (int, float))
        for token in tokens
    )


def observation_from_cache(record: dict[str, Any]) -> Observation:
    return Observation(
        lines=tuple(
            TextLine(token["text"], *token["bbox"], float(token["confidence"]))
            for token in record["tokens"]
        ),
        latency_ms=float(record.get("runtime_ms", 0.0)),
        engine=record["ocr_engine"],
        engine_version=record["ocr_engine_version"],
        cache_hit=True,
    )


def cache_record(page: PageRef, observation: Observation, engine_version: str) -> dict[str, Any]:
    return {
        **_expected_provenance(page, engine_version),
        "schema_version": "1.0",
        "source_asset_path": str(page.asset_path.resolve().relative_to(ROOT)),
        "source_page_id": page.page_id,
        "tokens": [
            {
                "text": line.text,
                "bbox": [line.x0, line.y0, line.x1, line.y1],
                "confidence": line.confidence,
            }
            for line in observation.lines
        ],
        "runtime_ms": observation.latency_ms,
        "cache_source": "LOCAL_REAL_SOURCE_REPLAY",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "OCR_EXECUTED",
    }


def valid_page_checkpoint(record: dict[str, Any], page: PageRef, engine_version: str) -> bool:
    provenance = record.get("ocr_provenance", {})
    expected = _expected_provenance(page, engine_version)
    return (
        all(provenance.get(key) == value for key, value in expected.items())
        and record.get("source_page_id") == page.page_id
        and record.get("source_page_sha256") == page.page_sha256
        and isinstance(record.get("candidate_class"), str)
        and isinstance(record.get("form_identity"), dict)
        and "localization_allowed" in record["form_identity"]
        and isinstance(record.get("routing_result"), dict)
    )


def safe_worker_count(requested: int, *, free_memory_mb: int, logical_cpus: int) -> int:
    configured = max(1, min(requested, 8))
    memory_cap = max(1, free_memory_mb // 768)
    cpu_cap = max(1, logical_cpus // 2)
    return min(configured, memory_cap, cpu_cap)


def available_memory_mb() -> int:
    return int(psutil.virtual_memory().available // (1024 * 1024))

def _worker_init() -> None:
    global _WORKER_OBSERVER
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
    _WORKER_OBSERVER = RapidOCRPageObserver(RapidOCRProvider(session_threads=1))


def _load_page(page: PageRef) -> Image.Image:
    with Image.open(page.asset_path) as source:
        source.seek(page.page_number - 1)
        image = source.copy()
    digest = hashlib.sha256()
    digest.update(f"{image.mode}|{image.width}|{image.height}|".encode())
    digest.update(image.tobytes())
    if digest.hexdigest() != page.page_sha256:
        raise ValueError("RENDERED_PAGE_HASH_MISMATCH")
    return image


def _fresh_ocr(page: PageRef) -> dict[str, Any]:
    if _WORKER_OBSERVER is None:
        _worker_init()
    assert _WORKER_OBSERVER is not None
    observation = asyncio.run(_WORKER_OBSERVER(_load_page(page), page))
    return {
        "lines": [asdict(line) for line in observation.lines],
        "latency_ms": observation.latency_ms,
        "engine": observation.engine,
        "engine_version": observation.engine_version,
    }


def _observation(value: dict[str, Any]) -> Observation:
    return Observation(
        tuple(TextLine(**line) for line in value["lines"]),
        float(value["latency_ms"]),
        value["engine"],
        value["engine_version"],
        False,
    )


def _page_result(
    page: PageRef,
    image: Image.Image,
    observation: Observation,
    router: MultiSignalRouter,
    engine_version: str,
    execution_status: str,
) -> dict[str, Any]:
    result = _safe_record(page, image, observation, router)
    result["ocr_provenance"] = _expected_provenance(page, engine_version)
    result["ocr_provenance"]["status"] = execution_status
    result["routing_result"] = {
        "route": result["candidate_class"],
        "identity_state": result["form_identity"]["identity_state"],
        "localization_allowed": result["form_identity"]["localization_allowed"],
    }
    return result


def _failure_result(page: PageRef, engine_version: str, error: BaseException) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "source_page_id": page.page_id,
        "source_page_sha256": page.page_sha256,
        "candidate_class": "UNKNOWN",
        "form_identity": {"identity_state": {}, "localization_allowed": False},
        "routing_result": {"route": "UNKNOWN", "localization_allowed": False},
        "ocr_provenance": {**_expected_provenance(page, engine_version), "status": "OCR_FAILED"},
        "failure": {"error_type": type(error).__name__, "message_persisted": False},
        "reason_codes": ["OBSERVATION_FAILED"],
    }


def _summary(
    pages: list[PageRef], records: list[dict[str, Any]], started: float, workers: int
) -> dict[str, Any]:
    elapsed = max(time.perf_counter() - started, 1e-9)
    completed = len(records)
    counts = Counter(record["candidate_class"] for record in records)
    identity_classes = (
        "CMS1500",
        "UB04",
        "OTHER_CLAIM_FORM",
        "UNKNOWN",
        "NON_CLAIM",
    )
    identity_distribution = {name: counts[name] for name in identity_classes}
    identity_distribution.update(
        {name: count for name, count in sorted(counts.items()) if name not in identity_distribution}
    )
    statuses = Counter(record["ocr_provenance"]["status"] for record in records)
    latencies = [
        float(record.get("ocr", {}).get("latency_ms", 0.0)) for record in records if "ocr" in record
    ]
    sorted_latency = sorted(latencies)

    def percentile(q: float) -> float | None:
        if not sorted_latency:
            return None
        return sorted_latency[min(len(sorted_latency) - 1, math.ceil(q * len(sorted_latency)) - 1)]

    rate = completed / elapsed * 60
    remaining = len(pages) - completed
    cache_hits = statuses["CACHE_HIT"]
    cms_localization_calls = sum(
        r["candidate_class"] == "CMS1500" and bool(r["form_identity"]["localization_allowed"])
        for r in records
    )
    ub_localization_calls = sum(
        r["candidate_class"] == "UB04" and bool(r["form_identity"]["localization_allowed"])
        for r in records
    )
    conflicting_identity_evidence = sum(
        any(bool(values) for values in r["form_identity"].get("conflicting_anchors", {}).values())
        for r in records
    )
    family_mismatch_blocks = sum(
        "STANDARD_IDENTITY_CLASSIFICATION_MISMATCH" in r.get("reason_codes", [])
        for r in records
    )
    return {
        "schema_version": "1.0",
        "runner_version": RUNNER_VERSION,
        "total_pages_discovered": len(pages),
        "pages_completed": completed,
        "pages_remaining": remaining,
        "cache_hits": cache_hits,
        "cache_hit_rate": cache_hits / completed if completed else 0.0,
        "fresh_ocr_executions": statuses["OCR_EXECUTED"],
        "ocr_failures": statuses["OCR_FAILED"],
        "retries": 0,
        "identity_distribution": identity_distribution,
        "canonical_localization_calls": cms_localization_calls + ub_localization_calls,
        "cms1500_localization_calls": cms_localization_calls,
        "ub04_localization_calls": ub_localization_calls,
        "other_claim_form_localization_calls": sum(
            r["candidate_class"] == "OTHER_CLAIM_FORM"
            and bool(r["form_identity"]["localization_allowed"])
            for r in records
        ),
        "unknown_localization_calls": sum(
            r["candidate_class"] in {"UNKNOWN", "SUPPORTING_DOCUMENT"}
            and bool(r["form_identity"]["localization_allowed"])
            for r in records
        ),
        "family_mismatch_blocks": family_mismatch_blocks,
        "conflicting_identity_evidence": conflicting_identity_evidence,
        "worker_count": workers,
        "wall_clock_seconds": elapsed,
        "effective_pages_per_minute": rate,
        "eta_seconds": remaining / rate * 60 if rate else None,
        "mean_ocr_runtime_ms": statistics.fmean(latencies) if latencies else None,
        "p50_ocr_runtime_ms": percentile(0.50),
        "p95_ocr_runtime_ms": percentile(0.95),
        "p99_ocr_runtime_ms": percentile(0.99),
        "peak_memory_mb": None,
        "peak_memory_status": "NOT_CAPTURED",
    }


def _canaries(router: MultiSignalRouter) -> list[dict[str, Any]]:
    image = Image.new("L", (1000, 1300), 255)
    draw = ImageDraw.Draw(image)
    for y in range(150, 1100, 100):
        draw.line((40, y, 960, y), fill=0, width=2)
    fixtures = [
        ("REIMBURSEMENT REQUEST", "PATIENT PROVIDER CLAIM", "TYPE OF BILL", "TOTAL CHARGES"),
        ("PROPRIETARY CLAIM FORM", "PATIENT CONTROL", "REVENUE CODE", "HCPCS UNITS TOTAL CHARGES"),
        ("LEGACY CLAIM FORM", "STATEMENT COVERS", "MEDICAL RECORD", "PRINCIPAL DIAGNOSIS"),
    ]
    results = []
    for index, values in enumerate(fixtures, 1):
        lines = [
            TextLine(value, 10, offset * 30, 500, offset * 30 + 20, 0.95)
            for offset, value in enumerate(values)
        ]
        decision = router.route(image, lines)
        results.append(
            {
                "canary": index,
                "route": decision.route.value,
                "ub04_rejected": decision.route is not MultiSignalRoute.UB04,
                "ub04_localization_calls": int(
                    decision.route is MultiSignalRoute.UB04 and decision.localization_allowed
                ),
            }
        )
    return results


def run_replay(
    source: Path,
    output: Path,
    report_dir: Path,
    archive_sha256: str,
    *,
    workers: int,
    limit: int | None = None,
) -> dict[str, Any]:
    router = MultiSignalRouter.load()
    canaries = _canaries(router)
    if not all(item["ub04_rejected"] and item["ub04_localization_calls"] == 0 for item in canaries):
        raise RuntimeError("FALSE_UB04_CANARY_FAILED")
    engine_version = rapidocr_version()
    pages = [page for page, _ in discover_pages(source, archive_sha256)]
    if limit is not None:
        pages = pages[:limit]
    output.mkdir(parents=True, exist_ok=True)
    page_dir, failure_dir, cache_dir = output / "pages", output / "failures", output / "ocr_cache"
    for directory in (page_dir, failure_dir, cache_dir):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "runner_version": RUNNER_VERSION,
        "archive_sha256": archive_sha256,
        "assets": len({page.asset_id for page in pages}),
        "rendered_pages": len(pages),
        "package_count": len({page.package_id for page in pages}),
        "input_manifest_sha256": _digest(
            "\n".join(f"{p.asset_sha256}:{p.page_number - 1}:{p.page_sha256}" for p in pages)
        ),
        "cache_key_version": CACHE_KEY_VERSION,
        "ocr_engine": "rapidocr",
        "ocr_engine_version": engine_version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "ocr_config_version": OCR_CONFIG_VERSION,
    }
    atomic_write_json(output / "manifest.json", manifest)
    records: list[dict[str, Any]] = []
    pending: list[PageRef] = []
    stale_rejected = 0
    for page in pages:
        checkpoint_path = page_dir / f"{page.page_id}.json"
        if checkpoint_path.exists():
            try:
                record = json.loads(checkpoint_path.read_text("utf-8"))
                if valid_page_checkpoint(record, page, engine_version):
                    records.append(record)
                    continue
                stale_rejected += 1
            except (OSError, json.JSONDecodeError):
                stale_rejected += 1
        pending.append(page)
    started = time.perf_counter()

    def complete(page: PageRef, observation: Observation, status: str) -> None:
        image = _load_page(page)
        record = _page_result(page, image, observation, router, engine_version, status)
        atomic_write_json(page_dir / f"{page.page_id}.json", record)
        records.append(record)
        if len(records) % SUMMARY_INTERVAL == 0:
            partial = _summary(pages, records, started, workers)
            partial["stale_records_rejected"] = stale_rejected
            atomic_write_json(output / "summary_partial.json", partial)

    fresh: list[PageRef] = []
    for page in pending:
        path = cache_dir / f"{ocr_cache_key(page, engine_version)}.json"
        if path.exists():
            try:
                cached = json.loads(path.read_text("utf-8"))
                if valid_cache_record(cached, page, engine_version):
                    complete(page, observation_from_cache(cached), "CACHE_HIT")
                    continue
                stale_rejected += 1
            except (OSError, json.JSONDecodeError):
                stale_rejected += 1
        fresh.append(page)

    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as pool:
        iterator = iter(fresh)
        active = {}
        for _ in range(min(len(fresh), workers * 2)):
            page = next(iterator, None)
            if page is not None:
                active[pool.submit(_fresh_ocr, page)] = page
        while active:
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                page = active.pop(future)
                try:
                    observation = _observation(future.result())
                    record = cache_record(page, observation, engine_version)
                    atomic_write_json(cache_dir / f"{record['cache_key']}.json", record)
                    complete(page, observation, "OCR_EXECUTED")
                except BaseException as error:  # noqa: BLE001 - isolate page failures
                    failed = _failure_result(page, engine_version, error)
                    atomic_write_json(failure_dir / f"{page.page_id}.json", failed)
                    records.append(failed)
                next_page = next(iterator, None)
                if next_page is not None:
                    active[pool.submit(_fresh_ocr, next_page)] = next_page
    records.sort(key=lambda record: record["source_page_id"])
    summary = _summary(pages, records, started, workers)
    summary.update(
        {
            "complete": len(records) == len(pages),
            "all_input_pages_accounted_for": len({r["source_page_id"] for r in records})
            == len(pages),
            "stale_records_rejected": stale_rejected,
            "cache_invalidations": stale_rejected,
            "canaries": canaries,
            "critical_routing_violations": (
                summary["other_claim_form_localization_calls"]
                + summary["unknown_localization_calls"]
                + sum(not item["ub04_rejected"] for item in canaries)
            ),
            "real_data_classification_accuracy": "NOT_EVALUABLE_WITHOUT_TRUSTED_LABELS",
            "manifest": manifest,
        }
    )
    atomic_write_json(output / "summary_partial.json", summary)
    if summary["complete"]:
        report_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(report_dir / "final_report.json", summary)
        markdown = [
            "# Strict identity replay final report",
            "",
            f"- Assets: {manifest['assets']}",
            f"- Rendered pages: {manifest['rendered_pages']}",
            f"- Cache hits: {summary['cache_hits']}",
            f"- Cache hit rate: {summary['cache_hit_rate']:.6f}",
            f"- Fresh OCR pages: {summary['fresh_ocr_executions']}",
            f"- OCR failures: {summary['ocr_failures']}",
            f"- Retries: {summary['retries']}",
            f"- Workers: {workers}",
            f"- Effective pages/minute: {summary['effective_pages_per_minute']:.3f}",
            f"- Mean OCR runtime (ms): {summary['mean_ocr_runtime_ms']}",
            f"- P50 OCR runtime (ms): {summary['p50_ocr_runtime_ms']}",
            f"- P95 OCR runtime (ms): {summary['p95_ocr_runtime_ms']}",
            f"- P99 OCR runtime (ms): {summary['p99_ocr_runtime_ms']}",
            "- Peak memory: NOT_CAPTURED",
            f"- Identity distribution: `{json.dumps(summary['identity_distribution'], sort_keys=True)}`",
            f"- CMS1500 localization calls: {summary['cms1500_localization_calls']}",
            f"- UB04 localization calls: {summary['ub04_localization_calls']}",
            f"- OTHER_CLAIM_FORM localization calls: {summary['other_claim_form_localization_calls']}",
            f"- UNKNOWN localization calls: {summary['unknown_localization_calls']}",
            f"- Family mismatch blocks: {summary['family_mismatch_blocks']}",
            f"- Conflicting identity evidence: {summary['conflicting_identity_evidence']}",
            f"- Critical routing violations: {summary['critical_routing_violations']}",
            f"- Stale cache records rejected: {summary['stale_records_rejected']}",
            f"- False-UB04 canaries: `{json.dumps(summary['canaries'], sort_keys=True)}`",
            "- Real-data classification accuracy: NOT_EVALUABLE_WITHOUT_TRUSTED_LABELS",
            "",
            "OCR-bearing cache records remain local under evaluation_data and are not committed.",
        ]
        (report_dir / "final_report.md").write_text("\n".join(markdown) + "\n", "utf-8")
    return summary


def finalize_existing_replay(output: Path, report_dir: Path) -> dict[str, Any]:
    """Publish the complete PHI-safe report without rerunning OCR."""
    original = json.loads((output / "summary_partial.json").read_text("utf-8"))
    records = []
    for directory in (output / "pages", output / "failures"):
        records.extend(
            json.loads(path.read_text("utf-8"))
            for path in sorted(directory.glob("*.json"))
        )
    total = int(original["total_pages_discovered"])
    page_ids = {record["source_page_id"] for record in records}
    if len(records) != total or len(page_ids) != total:
        raise RuntimeError("INCOMPLETE_REPLAY_CANNOT_BE_FINALIZED")

    started = time.perf_counter() - float(original["wall_clock_seconds"])
    summary = _summary([None] * total, records, started, int(original["worker_count"]))
    for key in (
        "complete",
        "all_input_pages_accounted_for",
        "stale_records_rejected",
        "canaries",
        "real_data_classification_accuracy",
        "manifest",
    ):
        summary[key] = original[key]
    summary["cache_invalidations"] = summary["stale_records_rejected"]
    summary["critical_routing_violations"] = (
        summary["other_claim_form_localization_calls"]
        + summary["unknown_localization_calls"]
        + sum(not item["ub04_rejected"] for item in summary["canaries"])
    )
    memory_path = output / "memory_peak.json"
    if memory_path.exists():
        memory = json.loads(memory_path.read_text("utf-8"))
        summary["peak_memory_mb"] = round(
            float(memory["peak_worker_tree_memory_bytes"]) / (1024 * 1024), 3
        )
        summary["peak_memory_status"] = "OBSERVED_DURING_PARTIAL_REPLAY_WINDOW"
        summary["memory_sampling_started_at"] = memory["sampling_started_at"]
        summary["memory_sample_interval_seconds"] = memory["sample_interval_seconds"]
    atomic_write_json(output / "summary_partial.json", summary)
    report_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_dir / "final_report.json", summary)
    markdown = [
        "# Strict identity replay final report",
        "",
        f"- Assets: {summary['manifest']['assets']}",
        f"- Rendered pages: {summary['manifest']['rendered_pages']}",
        f"- Package count: {summary['manifest']['package_count']}",
        f"- Input manifest SHA-256: {summary['manifest']['input_manifest_sha256']}",
        f"- Cache hits: {summary['cache_hits']}",
        f"- Cache hit rate: {summary['cache_hit_rate']:.6f}",
        f"- Fresh OCR pages: {summary['fresh_ocr_executions']}",
        f"- OCR failures: {summary['ocr_failures']}",
        f"- Retries: {summary['retries']}",
        f"- Workers: {summary['worker_count']}",
        f"- Wall-clock seconds: {summary['wall_clock_seconds']}",
        f"- Effective pages/minute: {summary['effective_pages_per_minute']:.3f}",
        f"- Mean OCR runtime (ms): {summary['mean_ocr_runtime_ms']}",
        f"- P50 OCR runtime (ms): {summary['p50_ocr_runtime_ms']}",
        f"- P95 OCR runtime (ms): {summary['p95_ocr_runtime_ms']}",
        f"- P99 OCR runtime (ms): {summary['p99_ocr_runtime_ms']}",
        f"- Peak memory: {summary['peak_memory_mb']} MB ({summary['peak_memory_status']})",
        f"- Identity distribution: `{json.dumps(summary['identity_distribution'], sort_keys=True)}`",
        f"- CMS1500 localization calls: {summary['cms1500_localization_calls']}",
        f"- UB04 localization calls: {summary['ub04_localization_calls']}",
        f"- OTHER_CLAIM_FORM localization calls: {summary['other_claim_form_localization_calls']}",
        f"- UNKNOWN localization calls: {summary['unknown_localization_calls']}",
        f"- Family mismatch blocks: {summary['family_mismatch_blocks']}",
        f"- Conflicting identity evidence: {summary['conflicting_identity_evidence']}",
        f"- Critical routing violations: {summary['critical_routing_violations']}",
        f"- Stale cache records rejected: {summary['stale_records_rejected']}",
        f"- False-UB04 canaries: `{json.dumps(summary['canaries'], sort_keys=True)}`",
        "- Real-data classification accuracy: NOT_EVALUABLE_WITHOUT_TRUSTED_LABELS",
        "",
        "OCR-bearing cache records remain local under evaluation_data and are not committed.",
    ]
    (report_dir / "final_report.md").write_text("\n".join(markdown) + "\n", "utf-8")
    return summary

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument(
        "--workers", type=int, default=int(os.getenv("STRICT_IDENTITY_REPLAY_WORKERS", "4"))
    )
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    workers = safe_worker_count(
        args.workers,
        free_memory_mb=available_memory_mb(),
        logical_cpus=os.cpu_count() or 1,
    )
    print(
        json.dumps(
            run_replay(
                args.source,
                args.output,
                args.report_dir,
                args.archive_sha256,
                workers=workers,
                limit=args.limit,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
