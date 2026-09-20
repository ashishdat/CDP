#!/usr/bin/env python3
"""Decide-only replay after LineChargeSelector + financial geometry.

Defaults target locked-50 integrity OCR. Pass ``--src-run`` / ``--out-dir`` for
broader remasure (e.g. hackathon-100c cascade artifacts).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.reprocess_field_hitl_decision_only import _process_decision_only
from scripts.run_hackathon_1000_cascade import (
    _append_ledger,
    _summarize,
    _utc_now,
    _write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src-run",
        type=Path,
        default=ROOT / "evaluation_results" / "hackathon_50_integrity_v1",
        help="Prior cascade/integrity run with OCRCandidates per claim",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "evaluation_results" / "hackathon_50_decide_line_charge_v1",
        help="Output directory for decide-only replay",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on documents (0 = all)",
    )
    args = parser.parse_args()

    src_run = args.src_run if args.src_run.is_absolute() else ROOT / args.src_run
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    workers = max(1, args.workers)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    ledger = out_dir / "results.jsonl"

    prior_by_doc: dict[str, dict] = {}
    for line in (src_run / "results.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            prior_by_doc[row["document"]] = row

    targets = sorted(prior_by_doc)
    if args.limit and args.limit > 0:
        targets = targets[: args.limit]
    print(
        f"decide_all n={len(targets)} workers={workers} src={src_run.name} out={out_dir.name}",
        flush=True,
    )
    lock = threading.Lock()
    rows: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
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
                    "disposition": "WORKER_ERROR",
                    "true_stp": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "ts": _utc_now(),
                }
            _append_ledger(ledger, row, lock=lock)
            with lock:
                rows.append(row)
            if i % 5 == 0 or i == len(targets) or row.get("true_stp"):
                stp = sum(1 for r in rows if r.get("true_stp"))
                print(
                    f"progress {i}/{len(targets)} {doc} -> {row.get('disposition')} "
                    f"stp={stp} blockers={row.get('critical_blockers')} "
                    f"elapsed={time.time() - t0:.0f}s",
                    flush=True,
                )

    by = {r["document"]: r for r in rows}
    uniq = list(by.values())
    summary = _summarize(uniq, limit=len(uniq))
    charge_auto = 0
    for r in uniq:
        fields = r.get("fields") or {}
        tc = fields.get("total_charge") or fields.get("total_charges") or {}
        if isinstance(tc, dict) and (
            tc.get("decision") in {"ACCEPT", "AUTO", "AUTO_ACCEPTED"}
            or tc.get("disp") in {"ACCEPT", "AUTO", "AUTO_ACCEPTED"}
            or tc.get("accepted")
        ):
            charge_auto += 1
        elif r.get("true_stp"):
            charge_auto += 1
    summary.update(
        {
            "reprocess": "decide_all_line_charge_selector_v1",
            "src_run": str(src_run),
            "charge_auto_heuristic": charge_auto,
            "elapsed_sec": round(time.time() - t0, 3),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT
            )
            .decode()
            .strip(),
        }
    )
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
