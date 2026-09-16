#!/usr/bin/env python3
"""Run field-cascade ops on the Hackathon Claims corpus (cascade strategy from YAML).

Operational completion / true-STP / HITL evaluation (no field-level GT).
Pipeline per claim: app.py (register+geometry+recovery ladder) → ocr → rank →
validate → assemble → complete (E3 from registration_report).

Resume-safe: JSONL ledger skips finished claim_ids.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.extraction_recovery.gap_taxonomy import classify_field_gap

DEFAULT_ZIP = ROOT / "data" / "Hackathon - 1000 Claims.zip"
DEFAULT_DATASET = ROOT / "dataset.yaml"
DEFAULT_OUT = ROOT / "evaluation_results" / "hackathon_1000_cascade_v9"

CRITICAL = (
    "patient_dob",
    "total_charge",
    "patient_name",
    "insured_id_number",
    "insured_name",
)
AUTO = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}
CASCADE_ENGINES = ("paddleocr", "rapidocr", "tesseract", "tesseract_digits")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bundle_id(document: str) -> str:
    """Group + claim family (e.g. Group A/M048DJJM) — multipage claim bundle."""
    text = (document or "").replace("\\", "/")
    if "/" in text:
        group, name = text.split("/", 1)
    else:
        group, name = "", text
    family = name.split(".")[0] if name else ""
    return f"{group}/{family}" if group else family


def _group_id(document: str) -> str:
    text = (document or "").replace("\\", "/")
    return text.split("/", 1)[0] if "/" in text else "UNKNOWN"


def _probe_ocr_engines() -> dict[str, Any]:
    """One-shot live probe: paddle / rapid / tesseract must OBSERVE, not UNAVAILABLE."""
    from PIL import Image, ImageDraw, ImageFont

    from packages.ocr_router import OCRRouter, OCRRouteRequest

    image = Image.new("L", (220, 64), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    draw.text((12, 18), "HELLO 123", fill=0, font=font)
    router = OCRRouter(lambda _attempt: True)
    result = router.route(
        OCRRouteRequest(
            image,
            (0, 0, image.width, image.height),
            engine_order=("paddleocr", "rapidocr", "tesseract"),
        )
    )
    # Force tesseract even when confirmation already satisfied.
    tess_only = router.route(
        OCRRouteRequest(
            image,
            (0, 0, image.width, image.height),
            engine_order=("tesseract",),
        )
    )
    observed = {
        attempt.engine: attempt.reason for attempt in result.attempts
    }
    observed["tesseract"] = (
        tess_only.selected.reason
        if tess_only.selected is not None
        else next((a.reason for a in tess_only.attempts if a.engine == "tesseract"), "MISSING")
    )
    return {
        "paddleocr": observed.get("paddleocr", "MISSING"),
        "rapidocr": observed.get("rapidocr", "MISSING"),
        "tesseract": observed.get("tesseract", "MISSING"),
        "all_observed": all(
            observed.get(name) == "OBSERVED"
            for name in ("paddleocr", "rapidocr", "tesseract")
        ),
        "tesseract_text": (
            " ".join(line.text for line in tess_only.selected.observation.lines)
            if tess_only.selected and tess_only.selected.observation
            else ""
        ),
    }


def _ocr_engine_stats(claim_out: Path) -> dict[str, Any]:
    """Count cascade OCR attempt outcomes from OCRCandidates.json."""
    path = claim_out / "ocr" / "OCRCandidates.json"
    attempts: Counter[str] = Counter()
    observed: Counter[str] = Counter()
    unavailable: Counter[str] = Counter()
    if not path.exists():
        return {
            "engines_attempted": {},
            "engines_observed": {},
            "engines_unavailable": {},
            "cascade_healthy": False,
            "tesseract_observed": 0,
            "tesseract_unavailable": 0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "engines_attempted": {},
            "engines_observed": {},
            "engines_unavailable": {},
            "cascade_healthy": False,
            "tesseract_observed": 0,
            "tesseract_unavailable": 0,
        }
    for field in payload.get("fields") or []:
        for attempt in field.get("attempts") or []:
            engine = str(attempt.get("engine") or "")
            if engine not in CASCADE_ENGINES:
                continue
            attempts[engine] += 1
            reason = str(attempt.get("reason") or "")
            if reason == "OBSERVED":
                observed[engine] += 1
            elif reason == "UNAVAILABLE":
                unavailable[engine] += 1
    # Healthy when primary paddle + confirmation rapid observed, and tesseract
    # never reported UNAVAILABLE (fill may be unused when first two succeed).
    healthy = (
        observed.get("paddleocr", 0) > 0
        and observed.get("rapidocr", 0) > 0
        and unavailable.get("tesseract", 0) == 0
    )
    return {
        "engines_attempted": dict(attempts),
        "engines_observed": dict(observed),
        "engines_unavailable": dict(unavailable),
        "cascade_healthy": healthy,
        "tesseract_observed": observed.get("tesseract", 0)
        + observed.get("tesseract_digits", 0),
        "tesseract_unavailable": unavailable.get("tesseract", 0),
    }

def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _list_documents(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        docs = [name for name in zf.namelist() if not name.endswith("/")]
    return sorted(docs)


def _load_done(ledger: Path) -> set[str]:
    done: set[str] = set()
    if not ledger.exists():
        return done
    with ledger.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            claim_id = str(row.get("claim_id") or "").strip()
            if claim_id and row.get("finished"):
                done.add(claim_id)
    return done


def _append_ledger(ledger: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _claim_slug(document: str) -> str:
    return document.replace("/", "__")


def _prune_document_json(app_out: Path) -> None:
    """Drop oversized document.json; keep registration_trace for OCR."""
    for path in app_out.glob("**/document.json"):
        try:
            path.unlink()
        except OSError:
            pass


def _prune_trace(app_out: Path) -> None:
    for path in app_out.glob("**/registration_trace.json"):
        try:
            path.unlink()
        except OSError:
            pass


def _stage_env() -> dict[str, str]:
    """Limit nested BLAS/OpenMP threads so parallel claim workers do not thrash."""
    env = dict(os.environ)
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "FLAGS_num_threads",
    ):
        env.setdefault(key, "1")
    return env


def _run_stage(cmd: list[str], log_path: Path) -> tuple[int, str]:
    """Stream stdout/stderr to a file to avoid pipe deadlocks with verbose app.py."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log_handle:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=_stage_env(),
        )
    tail = ""
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
    except OSError:
        pass
    return proc.returncode, tail


def _summarize_final(claim_out: Path) -> dict[str, Any]:
    final = json.loads((claim_out / "final" / "FinalClaim.json").read_text(encoding="utf-8"))
    decision = final.get("decision") or final
    fields: dict[str, Any] = {}
    for fd in decision.get("field_decisions") or []:
        name = fd.get("field_name")
        if name in CRITICAL:
            fields[name] = {
                "disp": fd.get("disposition"),
                "value": fd.get("selected_value"),
                "reasons": list(fd.get("reason_codes") or [])[:12],
            }
    ocr_path = claim_out / "ocr" / "OCRCandidates.json"
    service_line_charges = 0
    if ocr_path.exists():
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        service_line_charges = sum(
            1
            for line in (ocr.get("service_lines") or [])
            if line.get("status") == "OBSERVED" and line.get("charges")
        )
    blockers = list(decision.get("critical_blockers") or [])
    gaps = []
    for blocker in blockers:
        field_info = fields.get(blocker) or {}
        observed_text = str(field_info.get("value") or "")
        gap = classify_field_gap(
            blocker,
            observed_text=observed_text,
            accepted=False,
            service_line_charges=service_line_charges,
            reason_codes=field_info.get("reasons") or [],
        )
        if gap is not None:
            gaps.append(
                {
                    "field": gap.field_name,
                    "gap_class": gap.gap_class,
                    "action": gap.action,
                    "evidence": gap.evidence,
                }
            )
    completed = final.get("status") == "COMPLETED"
    review_required = bool(final.get("review_required") or decision.get("review_required"))
    engine_stats = _ocr_engine_stats(claim_out)
    return {
        "completed": completed,
        "review_required": review_required,
        "true_stp": completed and not review_required,
        "critical_blockers": blockers,
        "fields": fields,
        "gap_classes": gaps,
        "service_line_charges": service_line_charges,
        "claim_status": decision.get("claim_status") or final.get("claim_status"),
        "ocr_engine_stats": engine_stats,
    }


def _process_one(
    *,
    document: str,
    out_dir: Path,
    dataset_yaml: Path,
    document_type: str,
    keep_heavy: bool,
) -> dict[str, Any]:
    claim_id = _claim_slug(document)
    claim_out = out_dir / "claims" / claim_id
    if claim_out.exists():
        shutil.rmtree(claim_out)
    claim_out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    logs = claim_out / "logs"
    app_out = claim_out / "application"

    rc, tail = _run_stage(
        [
            sys.executable,
            str(ROOT / "app.py"),
            "--dataset",
            str(dataset_yaml),
            "--document",
            document,
            "--document-type",
            document_type,
            "--output-root",
            str(app_out),
        ],
        logs / "app.log",
    )

    geometry_hits = list(app_out.glob("**/GeometryResult.json"))
    if not geometry_hits:
        reason = "geometry_missing"
        for report in app_out.glob("**/registration_report.json"):
            try:
                payload = json.loads(report.read_text(encoding="utf-8"))
                reason = (
                    payload.get("reason")
                    or (payload.get("registration") or {}).get("reason")
                    or reason
                )
            except (OSError, json.JSONDecodeError):
                pass
            break
        for doc_json in app_out.glob("**/document.json"):
            try:
                payload = json.loads(doc_json.read_text(encoding="utf-8"))
                reg = payload.get("registration") or {}
                reason = reg.get("reason") or reason
            except (OSError, json.JSONDecodeError, ValueError):
                pass
            break
        if not keep_heavy:
            _prune_document_json(app_out)
            _prune_trace(app_out)
        disposition = "REGISTRATION_FAILED"
        if rc != 0 and reason == "geometry_missing":
            disposition = "APP_FAILURE"
        row = {
            "finished": True,
            "claim_id": claim_id,
            "document": document,
            "bundle_id": _bundle_id(document),
            "group_id": _group_id(document),
            "registration_ok": False,
            "completed": False,
            "true_stp": False,
            "disposition": disposition,
            "registration_reason": reason,
            "app_returncode": rc,
            "error": tail if disposition == "APP_FAILURE" else None,
            "elapsed_sec": round(time.time() - started, 3),
            "ts": _utc_now(),
        }
        _write_json(claim_out / "result.json", row)
        return row

    geometry_dir = geometry_hits[0].parent
    if not keep_heavy:
        _prune_document_json(app_out)

    stages = [
        (
            "ocr",
            [
                sys.executable,
                "-m",
                "scripts.ocr_from_geometry",
                str(geometry_dir),
                str(claim_out / "ocr"),
            ],
        ),
        (
            "rank",
            [
                sys.executable,
                "-m",
                "scripts.rank_from_ocr",
                str(claim_out / "ocr" / "OCRCandidates.json"),
                str(claim_out / "rank"),
            ],
        ),
        (
            "validate",
            [
                sys.executable,
                "-m",
                "scripts.validate_from_ranked",
                str(claim_out / "rank" / "RankedCandidates.json"),
                str(claim_out / "validate"),
                "--template-id",
                "cms1500",
                "--template-version",
                "02-12",
            ],
        ),
        (
            "assemble",
            [
                sys.executable,
                "-m",
                "scripts.assemble_extraction_result",
                str(claim_out / "ocr" / "OCRCandidates.json"),
                str(claim_out / "rank" / "RankedCandidates.json"),
                str(claim_out / "validate" / "ValidationResults.json"),
                str(claim_out / "extract"),
            ],
        ),
        (
            "complete",
            [
                sys.executable,
                "-m",
                "scripts.complete_from_extraction",
                str(claim_out / "extract" / "ExtractionResult.json"),
                str(claim_out / "final"),
                "--document-family",
                "CMS1500",
            ],
        ),
    ]
    for stage_name, cmd in stages:
        rc, tail = _run_stage(cmd, logs / f"{stage_name}.log")
        if stage_name == "ocr" and not keep_heavy:
            # Trace is only required for OCR; free disk after that stage.
            _prune_trace(app_out)
        if rc != 0:
            row = {
                "finished": True,
                "claim_id": claim_id,
                "document": document,
                "bundle_id": _bundle_id(document),
                "group_id": _group_id(document),
                "registration_ok": True,
                "completed": False,
                "true_stp": False,
                "disposition": "STAGE_FAILURE",
                "failed_stage": stage_name,
                "error": tail,
                "ocr_engine_stats": _ocr_engine_stats(claim_out),
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc_now(),
            }
            _write_json(claim_out / "result.json", row)
            return row

    try:
        summary = _summarize_final(claim_out)
    except Exception as exc:  # noqa: BLE001
        row = {
            "finished": True,
            "claim_id": claim_id,
            "document": document,
            "bundle_id": _bundle_id(document),
            "group_id": _group_id(document),
            "registration_ok": True,
            "completed": False,
            "true_stp": False,
            "disposition": "SUMMARY_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.time() - started, 3),
            "ts": _utc_now(),
        }
        _write_json(claim_out / "result.json", row)
        return row

    row = {
        "finished": True,
        "claim_id": claim_id,
        "document": document,
        "bundle_id": _bundle_id(document),
        "group_id": _group_id(document),
        "registration_ok": True,
        "completed": summary["completed"],
        "true_stp": summary["true_stp"],
        "review_required": summary["review_required"],
        "disposition": "TRUE_STP" if summary["true_stp"] else "HITL",
        "hitl_track": None if summary["true_stp"] else "FIELD_INK",
        "critical_blockers": summary["critical_blockers"],
        "fields": summary["fields"],
        "gap_classes": summary["gap_classes"],
        "service_line_charges": summary["service_line_charges"],
        "claim_status": summary["claim_status"],
        "ocr_engine_stats": summary.get("ocr_engine_stats") or {},
        "strategy_id": "field-cascade-v10",
        "elapsed_sec": round(time.time() - started, 3),
        "ts": _utc_now(),
    }
    _write_json(claim_out / "result.json", row)
    return row


def _rollup_scope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    reg_ok = sum(1 for r in rows if r.get("registration_ok"))
    completed = sum(1 for r in rows if r.get("completed"))
    true_stp = sum(1 for r in rows if r.get("true_stp"))
    hitl = sum(1 for r in rows if r.get("disposition") == "HITL")
    reg_hitl = sum(1 for r in rows if r.get("disposition") == "REGISTRATION_FAILED")
    field_hitl = sum(1 for r in rows if r.get("disposition") == "HITL" and r.get("completed"))
    return {
        "n": n,
        "registration_ok": reg_ok,
        "registration_ok_rate": round(reg_ok / n, 6) if n else 0.0,
        "completed": completed,
        "completion_rate": round(completed / n, 6) if n else 0.0,
        "true_stp": true_stp,
        "true_stp_rate_of_all": round(true_stp / n, 6) if n else 0.0,
        "true_stp_rate_of_completed": round(true_stp / completed, 6) if completed else 0.0,
        "hitl": hitl,
        "hitl_rate_of_all": round(hitl / n, 6) if n else 0.0,
        "registration_hitl": reg_hitl,
        "registration_hitl_rate": round(reg_hitl / n, 6) if n else 0.0,
        "field_ink_hitl": field_hitl,
        "field_ink_hitl_rate_of_completed": (
            round(field_hitl / completed, 6) if completed else 0.0
        ),
    }


def _summarize(rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    n = len(rows)
    by_disp = Counter(str(r.get("disposition") or "UNKNOWN") for r in rows)
    blockers: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    auto = {name: 0 for name in CRITICAL}
    reg_reasons: Counter[str] = Counter()
    engine_attempted: Counter[str] = Counter()
    engine_observed: Counter[str] = Counter()
    engine_unavailable: Counter[str] = Counter()
    cascade_healthy = 0
    cascade_claims = 0
    tesseract_claims = 0
    by_bundle: dict[str, list[dict[str, Any]]] = {}
    by_group: dict[str, list[dict[str, Any]]] = {}
    completed = sum(1 for r in rows if r.get("completed"))
    for row in rows:
        for b in row.get("critical_blockers") or []:
            blockers[str(b)] += 1
        for g in row.get("gap_classes") or []:
            gaps[str(g.get("gap_class"))] += 1
        if row.get("disposition") == "REGISTRATION_FAILED":
            reg_reasons[str(row.get("registration_reason") or "unknown")] += 1
        fields = row.get("fields") or {}
        for name in CRITICAL:
            disp = (fields.get(name) or {}).get("disp")
            if disp in AUTO:
                auto[name] += 1
        stats = row.get("ocr_engine_stats") or {}
        if stats:
            cascade_claims += 1
            if stats.get("cascade_healthy"):
                cascade_healthy += 1
            if int(stats.get("tesseract_observed") or 0) > 0:
                tesseract_claims += 1
            for eng, count in (stats.get("engines_attempted") or {}).items():
                engine_attempted[str(eng)] += int(count)
            for eng, count in (stats.get("engines_observed") or {}).items():
                engine_observed[str(eng)] += int(count)
            for eng, count in (stats.get("engines_unavailable") or {}).items():
                engine_unavailable[str(eng)] += int(count)
        doc = str(row.get("document") or "")
        bundle = str(row.get("bundle_id") or _bundle_id(doc))
        group = str(row.get("group_id") or _group_id(doc))
        by_bundle.setdefault(bundle, []).append(row)
        by_group.setdefault(group, []).append(row)

    overall = _rollup_scope(rows)
    return {
        "dataset": "DEVELOPMENT_DATASET_V1 / Hackathon - 1000 Claims.zip",
        "document_count_requested": limit,
        "document_count_evaluated": n,
        "strategy_id": "field-cascade-v10",
        **overall,
        "disposition_counts": dict(by_disp),
        "registration_failure_reasons": dict(reg_reasons),
        "critical_blockers": dict(blockers),
        "gap_classes": dict(gaps),
        "field_auto_of_completed": {
            name: f"{auto[name]}/{completed}" for name in CRITICAL
        },
        "field_auto_rate_of_completed": {
            name: round(auto[name] / completed, 6) if completed else 0.0
            for name in CRITICAL
        },
        "accuracy": {
            "status": "UNAVAILABLE_NO_GROUND_TRUTH",
            "end_to_end_correct_completion_rate": None,
            "field_accuracy": None,
            "note": (
                "Hackathon 1000 ZIP has no field-level labels. Accuracy cannot be "
                "scored; report operational STP/HITL and field auto-accept rates only."
            ),
        },
        "ocr_cascade": {
            "claims_with_ocr": cascade_claims,
            "cascade_healthy_claims": cascade_healthy,
            "cascade_healthy_rate": (
                round(cascade_healthy / cascade_claims, 6) if cascade_claims else 0.0
            ),
            "claims_with_tesseract_observed": tesseract_claims,
            "engines_attempted": dict(engine_attempted),
            "engines_observed": dict(engine_observed),
            "engines_unavailable": dict(engine_unavailable),
            "required": (
                "paddleocr OBSERVED + rapidocr OBSERVED; tesseract fill on miss "
                "(never UNAVAILABLE)"
            ),
        },
        "by_group": {
            group: _rollup_scope(group_rows)
            for group, group_rows in sorted(by_group.items())
        },
        "by_bundle": {
            bundle: _rollup_scope(bundle_rows)
            for bundle, bundle_rows in sorted(
                by_bundle.items(), key=lambda item: (-len(item[1]), item[0])
            )
        },
        "bundle_count": len(by_bundle),
        "note": (
            "Operational metrics under field-cascade-v10 with paddle+rapid confirmation "
            "cascade and agreement-aware pick. No field-level GT on Hackathon corpus — "
            "accuracy marked unavailable."
        ),
        "generated_at": _utc_now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--document-type", default="CMS1500")
    parser.add_argument("--keep-heavy", action="store_true")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "results.jsonl"
    lock = threading.Lock()

    try:
        engine_probe = _probe_ocr_engines()
    except Exception as exc:  # noqa: BLE001
        engine_probe = {
            "paddleocr": "ERROR",
            "rapidocr": "ERROR",
            "tesseract": "ERROR",
            "all_observed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(out_dir / "engines_probe.json", engine_probe)
    print(f"engines_probe={json.dumps(engine_probe)}", flush=True)
    if not engine_probe.get("all_observed"):
        print(
            "WARNING: OCR engine probe incomplete — cascade fill may degrade",
            flush=True,
        )

    docs = _list_documents(args.zip)
    selected = docs[args.offset : args.offset + args.limit]
    done = _load_done(ledger) if args.resume else set()
    pending = [d for d in selected if _claim_slug(d) not in done]
    print(
        f"strategy=field-cascade-v10 selected={len(selected)} "
        f"already_done={len(selected) - len(pending)} pending={len(pending)} "
        f"workers={args.workers}",
        flush=True,
    )

    rows_new: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                _process_one,
                document=document,
                out_dir=out_dir,
                dataset_yaml=args.dataset,
                document_type=args.document_type,
                keep_heavy=args.keep_heavy,
            ): document
            for document in pending
        }
        for i, fut in enumerate(as_completed(futures), start=1):
            document = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001
                row = {
                    "finished": True,
                    "claim_id": _claim_slug(document),
                    "document": document,
                    "bundle_id": _bundle_id(document),
                    "group_id": _group_id(document),
                    "registration_ok": False,
                    "completed": False,
                    "true_stp": False,
                    "disposition": "WORKER_ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                    "ts": _utc_now(),
                }
            _append_ledger(ledger, row, lock)
            rows_new.append(row)
            if i % 5 == 0 or i == len(futures):
                stp = sum(1 for r in rows_new if r.get("true_stp"))
                reg = sum(1 for r in rows_new if r.get("registration_ok"))
                print(
                    f"progress {i}/{len(futures)} newest={row.get('claim_id')} "
                    f"batch_reg={reg}/{len(rows_new)} batch_true_stp={stp}/{len(rows_new)} "
                    f"disp={row.get('disposition')}",
                    flush=True,
                )

    all_rows: list[dict[str, Any]] = []
    if ledger.exists():
        with ledger.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    by_id: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        cid = str(row.get("claim_id") or "")
        if cid:
            by_id[cid] = row
    final_rows = [by_id[_claim_slug(d)] for d in selected if _claim_slug(d) in by_id]
    summary = _summarize(final_rows, limit=len(selected))
    summary["workers"] = args.workers
    summary["engines_probe"] = engine_probe
    try:
        summary["out_dir"] = str(out_dir.relative_to(ROOT))
    except ValueError:
        summary["out_dir"] = str(out_dir)
    summary_path = out_dir / "summary.json"
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
