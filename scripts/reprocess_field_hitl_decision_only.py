#!/usr/bin/env python3
"""Fast field-HITL reprocess: reuse OCRCandidates, re-run rank→complete only.

v11.1 Track-B fixes (name confusable/MI, tesseract engine auth) live in
reconciler / evidence decision — they do not require re-OCR. This path finishes
~107 claims in minutes instead of hours of paddle cold-starts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_hackathon_1000_cascade import (
    _append_ledger,
    _claim_slug,
    _run_stage,
    _summarize,
    _summarize_final,
    _utc_now,
    _write_json,
)


def _process_decision_only(
    *,
    document: str,
    src_run: Path,
    out_dir: Path,
    prior_row: dict[str, Any],
) -> dict[str, Any]:
    claim_id = _claim_slug(document)
    src_claim = src_run / "claims" / claim_id
    claim_out = out_dir / "claims" / claim_id
    if claim_out.exists():
        shutil.rmtree(claim_out)
    claim_out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    logs = claim_out / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    src_ocr = src_claim / "ocr" / "OCRCandidates.json"
    if not src_ocr.exists():
        row = {
            "finished": True,
            "claim_id": claim_id,
            "document": document,
            "disposition": "OCR_MISSING",
            "true_stp": False,
            "prior_disposition": prior_row.get("disposition"),
            "elapsed_sec": round(time.time() - started, 3),
            "ts": _utc_now(),
            "reprocess": "decision_only_v11_1",
        }
        _write_json(claim_out / "result.json", row)
        return row

    ocr_dir = claim_out / "ocr"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_ocr, ocr_dir / "OCRCandidates.json")
    src_tel = src_claim / "ocr" / "ocr_telemetry.json"
    if src_tel.exists():
        shutil.copy2(src_tel, ocr_dir / "ocr_telemetry.json")

    stages = [
        (
            "rank",
            [
                sys.executable,
                "-m",
                "scripts.rank_from_ocr",
                str(ocr_dir / "OCRCandidates.json"),
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
                str(ocr_dir / "OCRCandidates.json"),
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
                "error": tail[-500:],
                "prior_disposition": prior_row.get("disposition"),
                "prior_true_stp": prior_row.get("true_stp"),
                "prior_blockers": prior_row.get("critical_blockers"),
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc_now(),
                "reprocess": "decision_only_v11_1",
            }
            _write_json(claim_out / "result.json", row)
            return row

    summary = _summarize_final(claim_out)
    row = {
        "finished": True,
        "claim_id": claim_id,
        "document": document,
        "registration_ok": True,
        "completed": summary["completed"],
        "true_stp": summary["true_stp"],
        "review_required": summary["review_required"],
        "disposition": "TRUE_STP" if summary["true_stp"] else "HITL",
        "critical_blockers": summary.get("critical_blockers"),
        "gap_classes": summary.get("gap_classes"),
        "fields": summary.get("fields"),
        "service_line_charges": summary.get("service_line_charges"),
        "prior_disposition": prior_row.get("disposition"),
        "prior_true_stp": prior_row.get("true_stp"),
        "prior_blockers": prior_row.get("critical_blockers"),
        "elapsed_sec": round(time.time() - started, 3),
        "ts": _utc_now(),
        "reprocess": "decision_only_v11_1",
    }
    _write_json(claim_out / "result.json", row)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src-run",
        type=Path,
        default=ROOT / "evaluation_results" / "hackathon_300_cascade_v11",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT
        / "evaluation_results"
        / "hackathon_300_field_hitl_decision_reprocess_v11_1",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    src_run = args.src_run if args.src_run.is_absolute() else ROOT / args.src_run
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    ledger = out_dir / "results.jsonl"

    prior_by_doc: dict[str, dict[str, Any]] = {}
    for line in (src_run / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prior_by_doc[row["document"]] = row

    targets = sorted(
        doc
        for doc, row in prior_by_doc.items()
        if row.get("disposition") == "HITL"
    )
    if args.limit and args.limit > 0:
        targets = targets[: args.limit]

    print(
        f"decision_only targets={len(targets)} workers={args.workers}",
        flush=True,
    )
    lock = threading.Lock()
    rows: list[dict[str, Any]] = []
    flipped = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {
            pool.submit(
                _process_decision_only,
                document=doc,
                src_run=src_run,
                out_dir=out_dir,
                prior_row=prior_by_doc[doc],
            ): doc
            for doc in targets
        }
        for i, fut in enumerate(as_completed(futs), 1):
            doc = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001
                row = {
                    "finished": True,
                    "document": doc,
                    "claim_id": _claim_slug(doc),
                    "disposition": "WORKER_ERROR",
                    "true_stp": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "ts": _utc_now(),
                    "reprocess": "decision_only_v11_1",
                }
            _append_ledger(ledger, row, lock=lock)
            with lock:
                rows.append(row)
                if row.get("true_stp") and not row.get("prior_true_stp"):
                    flipped += 1
            if i % 10 == 0 or i == len(targets) or row.get("true_stp"):
                print(
                    f"progress {i}/{len(targets)} {doc} "
                    f"{row.get('prior_disposition')}->{row.get('disposition')} "
                    f"blockers={row.get('critical_blockers')} "
                    f"flipped={flipped} "
                    f"elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )

    by = {r["document"]: r for r in rows}
    uniq = list(by.values())
    summary = _summarize(uniq, limit=len(uniq))
    summary.update(
        {
            "reprocess": "decision_only_v11_1",
            "src_run": str(src_run),
            "flipped_to_true_stp": flipped,
            "still_hitl": sum(1 for r in uniq if r.get("disposition") == "HITL"),
            "stage_failures": sum(
                1
                for r in uniq
                if r.get("disposition")
                in {"STAGE_FAILURE", "WORKER_ERROR", "OCR_MISSING"}
            ),
            "elapsed_sec": round(time.time() - t0, 3),
        }
    )
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
