#!/usr/bin/env python3
"""Run field-cascade-v8 ops on the Hackathon 1000 Claims corpus.

Operational completion / true-STP / HITL evaluation (no field-level GT).
Pipeline per claim: app.py (register+geometry+recovery ladder) → ocr → rank →
validate → assemble → complete (E3 from registration_report).

Resume-safe: JSONL ledger skips finished claim_ids.
"""

from __future__ import annotations

import argparse
import json
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
DEFAULT_OUT = ROOT / "evaluation_results" / "hackathon_1000_cascade_v8"

CRITICAL = (
    "patient_dob",
    "total_charge",
    "patient_name",
    "insured_id_number",
    "insured_name",
)
AUTO = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return {
        "completed": completed,
        "review_required": review_required,
        "true_stp": completed and not review_required,
        "critical_blockers": blockers,
        "fields": fields,
        "gap_classes": gaps,
        "service_line_charges": service_line_charges,
        "claim_status": decision.get("claim_status") or final.get("claim_status"),
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
                "registration_ok": True,
                "completed": False,
                "true_stp": False,
                "disposition": "STAGE_FAILURE",
                "failed_stage": stage_name,
                "error": tail,
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
        "registration_ok": True,
        "completed": summary["completed"],
        "true_stp": summary["true_stp"],
        "review_required": summary["review_required"],
        "disposition": "TRUE_STP" if summary["true_stp"] else "HITL",
        "critical_blockers": summary["critical_blockers"],
        "fields": summary["fields"],
        "gap_classes": summary["gap_classes"],
        "service_line_charges": summary["service_line_charges"],
        "claim_status": summary["claim_status"],
        "strategy_id": "field-cascade-v8",
        "elapsed_sec": round(time.time() - started, 3),
        "ts": _utc_now(),
    }
    _write_json(claim_out / "result.json", row)
    return row


def _summarize(rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    n = len(rows)
    reg_ok = sum(1 for r in rows if r.get("registration_ok"))
    completed = sum(1 for r in rows if r.get("completed"))
    true_stp = sum(1 for r in rows if r.get("true_stp"))
    by_disp = Counter(str(r.get("disposition") or "UNKNOWN") for r in rows)
    blockers: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    auto = {name: 0 for name in CRITICAL}
    reg_reasons: Counter[str] = Counter()
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
    denom = max(completed, 1)
    return {
        "dataset": "DEVELOPMENT_DATASET_V1 / Hackathon - 1000 Claims.zip",
        "document_count_requested": limit,
        "document_count_evaluated": n,
        "strategy_id": "field-cascade-v8",
        "registration_ok": reg_ok,
        "registration_fail": n - reg_ok,
        "registration_ok_rate": round(reg_ok / n, 6) if n else 0.0,
        "completed": completed,
        "completion_rate": round(completed / n, 6) if n else 0.0,
        "true_stp": true_stp,
        "true_stp_rate_of_all": round(true_stp / n, 6) if n else 0.0,
        "true_stp_rate_of_completed": round(true_stp / denom, 6) if completed else 0.0,
        "hitl_completed": completed - true_stp,
        "disposition_counts": dict(by_disp),
        "registration_failure_reasons": dict(reg_reasons),
        "critical_blockers": dict(blockers),
        "gap_classes": dict(gaps),
        "field_auto_of_completed": {
            name: f"{auto[name]}/{completed}" for name in CRITICAL
        },
        "note": (
            "No field-level ground truth for Hackathon 1000; "
            "metrics are registration / completion / true STP / HITL under field-cascade-v8 "
            "(E3 plumbing, registration recovery ladder, Track-B DOB/charge cascade)."
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

    docs = _list_documents(args.zip)
    selected = docs[args.offset : args.offset + args.limit]
    done = _load_done(ledger) if args.resume else set()
    pending = [d for d in selected if _claim_slug(d) not in done]
    print(
        f"strategy=field-cascade-v8 selected={len(selected)} "
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
