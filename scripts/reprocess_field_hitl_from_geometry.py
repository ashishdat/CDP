#!/usr/bin/env python3
"""Reprocess field-HITL cascade claims after Track-B fixes (reuse geometry).

Skips app.py registration: copies GeometryResult from a prior run, then runs
ocr → rank → validate → assemble → complete under the current cascade wiring.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_hackathon_1000_cascade import (  # noqa: E402
    _append_ledger,
    _claim_slug,
    _ocr_engine_stats,
    _run_stage,
    _summarize,
    _summarize_final,
    _utc_now,
    _write_json,
)


def _find_geometry(src_claim: Path) -> Path | None:
    hits = list(src_claim.glob("**/GeometryResult.json"))
    return hits[0].parent if hits else None


def _process_reuse(
    *,
    document: str,
    src_run: Path,
    out_dir: Path,
    prior_row: dict[str, Any] | None,
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

    geo_src = _find_geometry(src_claim) if src_claim.exists() else None
    if geo_src is None:
        row = {
            "finished": True,
            "claim_id": claim_id,
            "document": document,
            "registration_ok": False,
            "completed": False,
            "true_stp": False,
            "disposition": "GEOMETRY_MISSING",
            "prior_disposition": (prior_row or {}).get("disposition"),
            "elapsed_sec": round(time.time() - started, 3),
            "ts": _utc_now(),
        }
        _write_json(claim_out / "result.json", row)
        return row

    app_out = claim_out / "application"
    app_out.mkdir(parents=True, exist_ok=True)
    # Copy geometry tree only (enough for OCR).
    dest_geo = app_out / geo_src.name
    shutil.copytree(geo_src, dest_geo)
    # Original cascade prunes registration_trace after OCR; OCR only needs
    # the CMS1500 reference size from the Input-image coverage observation.
    trace_path = dest_geo / "registration_trace.json"
    if not trace_path.exists():
        _write_json(
            trace_path,
            {
                "traces": [
                    {
                        "events": [
                            {
                                "data": {
                                    "coverage_observation": {
                                        "stage": "Input image",
                                        "reference": {"size": [1700, 2200]},
                                    }
                                }
                            }
                        ]
                    }
                ]
            },
        )

    stages = [
        (
            "ocr",
            [
                sys.executable,
                "-m",
                "scripts.ocr_from_geometry",
                str(dest_geo),
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
                "prior_disposition": (prior_row or {}).get("disposition"),
                "prior_true_stp": (prior_row or {}).get("true_stp"),
                "ocr_engine_stats": _ocr_engine_stats(claim_out),
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc_now(),
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
        "prior_disposition": (prior_row or {}).get("disposition"),
        "prior_true_stp": (prior_row or {}).get("true_stp"),
        "prior_blockers": (prior_row or {}).get("critical_blockers"),
        "ocr_engine_stats": _ocr_engine_stats(claim_out),
        "elapsed_sec": round(time.time() - started, 3),
        "ts": _utc_now(),
        "reprocess": "field_hitl_from_geometry_v11_1",
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
        default=ROOT / "evaluation_results" / "hackathon_300_field_hitl_reprocess_v11_1",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip documents already present in out-dir results.jsonl",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    os.environ.setdefault("CDP_OCR_FIELD_SCOPE", "stp_critical")

    src_run = args.src_run if args.src_run.is_absolute() else ROOT / args.src_run
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "results.jsonl"

    prior_by_doc: dict[str, dict[str, Any]] = {}
    for line in (src_run / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prior_by_doc[row["document"]] = row

    targets = [
        doc
        for doc, row in prior_by_doc.items()
        if row.get("disposition") == "HITL" and row.get("registration_ok", True)
    ]
    targets.sort()

    done: set[str] = set()
    if args.resume and ledger.exists():
        for line in ledger.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["document"])

    pending = [d for d in targets if d not in done]
    if args.limit and args.limit > 0:
        pending = pending[: args.limit]

    print(
        f"field_hitl_targets={len(targets)} already_done={len(done)} "
        f"pending={len(pending)} workers={args.workers} "
        f"scope={os.environ.get('CDP_OCR_FIELD_SCOPE')}",
        flush=True,
    )

    lock = threading.Lock()
    rows: list[dict[str, Any]] = []
    if args.resume and ledger.exists():
        for line in ledger.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))

    flipped = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {
            pool.submit(
                _process_reuse,
                document=doc,
                src_run=src_run,
                out_dir=out_dir,
                prior_row=prior_by_doc.get(doc),
            ): doc
            for doc in pending
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
                }
            _append_ledger(ledger, row, lock=lock)
            with lock:
                rows.append(row)
                if row.get("true_stp") and not row.get("prior_true_stp"):
                    flipped += 1
            print(
                f"progress {i}/{len(pending)} {doc} "
                f"prior={row.get('prior_disposition')} -> {row.get('disposition')} "
                f"blockers={row.get('critical_blockers')} "
                f"flipped_so_far={flipped}",
                flush=True,
            )

    # Unique latest per document
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        by[r["document"]] = r
    uniq = list(by.values())
    summary = _summarize(uniq, limit=len(uniq))
    summary["reprocess"] = "field_hitl_from_geometry_v11_1"
    summary["src_run"] = str(src_run)
    summary["flipped_to_true_stp"] = sum(
        1 for r in uniq if r.get("true_stp") and not r.get("prior_true_stp")
    )
    summary["still_hitl"] = sum(1 for r in uniq if r.get("disposition") == "HITL")
    summary["stage_failures"] = sum(
        1 for r in uniq if r.get("disposition") in {"STAGE_FAILURE", "WORKER_ERROR", "GEOMETRY_MISSING"}
    )
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
