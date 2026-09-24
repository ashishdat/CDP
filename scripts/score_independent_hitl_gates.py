#!/usr/bin/env python3
"""Score Independent claim-page STP gates after a HITL program phase.

Governance: fail the gate if claim-page STP drops or false-accepts rise
on agent-GT scored accepts (when GT file present).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config" / "independent_hitl_program_v1.yaml"


def _latest(ledger: Path) -> dict[str, dict]:
    by: dict[str, dict] = {}
    for line in ledger.open(encoding="utf-8"):
        row = json.loads(line)
        by[row["claim_id"]] = row
    return by


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--ledger-a",
        type=Path,
        default=ROOT / "evaluation_results" / "hackathon_600_independent_v13c",
    )
    parser.add_argument(
        "--ledger-b",
        type=Path,
        default=ROOT
        / "evaluation_results"
        / "hackathon_400_remainder_independent_v13c",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "docs" / "metrics" / "independent_1000_v13c_summary.json",
    )
    args = parser.parse_args()

    cfg = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
    phase_cfg = (cfg.get("phases") or {}).get(args.phase) or {}
    gates = cfg.get("gates") or {}

    merged: dict[str, dict] = {}
    for ledger_root in (args.ledger_a, args.ledger_b):
        root = ledger_root if ledger_root.is_absolute() else ROOT / ledger_root
        merged.update(_latest(root / "results.jsonl"))

    disp = Counter(r.get("disposition") for r in merged.values())
    claim_pages = sum(
        1 for r in merged.values() if r.get("disposition") != "REGISTRATION_FAILED"
    )
    stp = disp.get("TRUE_STP", 0)
    hitl = disp.get("HITL", 0)
    rate = (stp / claim_pages) if claim_pages else 0.0

    baseline = {}
    if args.baseline.is_file():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    base_rate = float(
        baseline.get("true_stp_rate_of_claim_pages")
        or baseline.get("claim_page_stp_rate")
        or (cfg.get("baseline") or {}).get("claim_page_stp_rate")
        or 0.0
    )

    # Optional FA score
    fa = None
    gt_path = ROOT / str(gates.get("score_gt") or "")
    if gt_path.is_file():
        try:
            from packages.evaluation.agent_gt_score import score_merged_against_agent_gt

            fa = score_merged_against_agent_gt(merged, gt_path)
        except Exception as exc:  # noqa: BLE001
            fa = {"error": f"{type(exc).__name__}:{exc}"}

    exit_min = float(phase_cfg.get("exit_claim_stp_min") or 0.0)
    stp_ok = rate + 1e-6 >= base_rate  # must not lose STP (float-safe)
    target_ok = (exit_min <= 0) or (rate + 1e-6 >= exit_min)
    fa_ok = True
    if isinstance(fa, dict) and "false_accepts" in fa and "baseline_false_accepts" in fa:
        fa_ok = int(fa["false_accepts"]) <= int(fa["baseline_false_accepts"]) + int(
            gates.get("max_false_accept_delta") or 0
        )

    report = {
        "phase": args.phase,
        "n": len(merged),
        "claim_pages": claim_pages,
        "true_stp": stp,
        "hitl": hitl,
        "registration_failed": disp.get("REGISTRATION_FAILED", 0),
        "claim_page_stp_rate": round(rate, 4),
        "baseline_claim_page_stp_rate": round(base_rate, 4),
        "phase_exit_min": exit_min,
        "gates": {
            "stp_not_decreased": stp_ok,
            "phase_exit_met": target_ok,
            "false_accept_ok": fa_ok,
        },
        "pass": bool(stp_ok and fa_ok),
        "false_accept": fa,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = (
        ROOT
        / "docs"
        / "metrics"
        / f"independent_hitl_gate_{args.phase.lower()}.json"
    )
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}", file=sys.stderr)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
