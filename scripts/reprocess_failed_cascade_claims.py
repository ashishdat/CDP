#!/usr/bin/env python3
"""Reprocess specific cascade claims after algorithm fixes (failed-HITL retest)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_hackathon_1000_cascade import (
    DEFAULT_DATASET,
    _append_ledger,
    _process_one,
    _summarize,
    _write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claims",
        nargs="+",
        required=True,
        help="Document paths e.g. 'Group A/M048DJJF.002'",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "evaluation_results" / "hackathon_1000_cascade_v9_retest",
    )
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    ledger = out_dir / "results.jsonl"
    rows = []
    for document in args.claims:
        print(f"retest {document}", flush=True)
        row = _process_one(
            document=document,
            out_dir=out_dir,
            dataset_yaml=DEFAULT_DATASET,
            document_type="CMS1500",
            keep_heavy=False,
        )
        _append_ledger(ledger, row, lock=__import__("threading").Lock())
        rows.append(row)
        print(
            f"  disp={row.get('disposition')} stp={row.get('true_stp')} "
            f"blockers={row.get('critical_blockers')}",
            flush=True,
        )
    summary = _summarize(rows, limit=len(rows))
    summary["retest_claims"] = list(args.claims)
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
