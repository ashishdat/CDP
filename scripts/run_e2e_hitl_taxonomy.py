#!/usr/bin/env python3
"""E2E HITL taxonomy over a completed ops run — catch stacked fail-closed gaps."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def classify_claim(claim_dir: Path) -> dict:
    dec = json.loads((claim_dir / "final" / "DecisionResult.json").read_text())
    result = json.loads((claim_dir / "result.json").read_text())
    cd = dec.get("claim_decision") or {}
    contras = cd.get("contradictions") or []
    blockers = dec.get("critical_blockers") or []
    tc = None
    for fd in dec.get("field_decisions") or []:
        if fd.get("field_name") == "total_charge":
            tc = fd
            break
    reasons = set((tc or {}).get("reason_codes") or [])
    disp = (tc or {}).get("disposition")
    if result.get("true_stp"):
        bucket = "true_stp"
    elif disp == "AUTO_ACCEPTED" and any("dob" in str(b).lower() for b in blockers):
        bucket = "identity_dob"
    elif disp == "AUTO_ACCEPTED" and any("id" in str(b).lower() for b in blockers):
        bucket = "identity_id"
    elif disp == "AUTO_ACCEPTED" and "CLAIM_TOTAL_CONTRADICTION" in contras:
        # Field AUTO without monetary CONFIRMED — true Box28↔Σ conflict.
        bucket = "true_box28_line_disagree"
    elif "CONFLICT_MARGIN_TOO_SMALL" in reasons:
        bucket = "charge_conflict_margin"
    elif "BLEED_CENTS_FAIL_CLOSED" in reasons:
        bucket = "bleed_fail_closed"
    elif disp != "AUTO_ACCEPTED":
        bucket = "charge_field_hitl"
    else:
        bucket = "other_hitl"
    return {
        "claim_id": claim_dir.name,
        "bucket": bucket,
        "true_stp": bool(result.get("true_stp")),
        "total_charge_disp": disp,
        "total_charge_value": (tc or {}).get("selected_value"),
        "blockers": blockers,
        "claim_contradictions": contras,
        "charge_reasons": sorted(reasons)[:12],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        default="evaluation_results/hackathon_1000_stp_recovery_e2e_authority_v1",
    )
    parser.add_argument(
        "--out",
        default="docs/metrics/stp_hitl_taxonomy_latest.json",
    )
    args = parser.parse_args()
    run = ROOT / args.run
    rows = []
    for claim_dir in sorted((run / "claims").iterdir()):
        if not (claim_dir / "result.json").exists():
            continue
        if not (claim_dir / "final" / "DecisionResult.json").exists():
            continue
        rows.append(classify_claim(claim_dir))
    buckets = Counter(r["bucket"] for r in rows)
    hitl_ids = defaultdict(list)
    for r in rows:
        if r["bucket"] != "true_stp":
            hitl_ids[r["bucket"]].append(r["claim_id"])
    completed = len(rows)
    true_stp = buckets.get("true_stp", 0)
    summary = {
        "title": "E2E HITL taxonomy (full ops cohort)",
        "run": str(run.relative_to(ROOT)),
        "completed": completed,
        "true_stp": true_stp,
        "true_stp_rate": round(true_stp / completed, 6) if completed else 0.0,
        "hitl": completed - true_stp,
        "buckets": dict(buckets),
        "hitl_ids": {k: v for k, v in hitl_ids.items()},
        "invariant": (
            "AUTO total_charge with CLAIM_TOTAL_CONFIRMED/CASH_RULING/"
            "CHARGE_TOTAL_AUTHORITY must never remain in true_box28_line_disagree "
            "or other_hitl solely due to CLAIM_TOTAL_CONTRADICTION."
        ),
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    # Fail if the invariant is violated.
    for r in rows:
        if r["bucket"] != "true_stp" and r["total_charge_disp"] == "AUTO_ACCEPTED":
            codes = set(r["charge_reasons"])
            if codes & {
                "CLAIM_TOTAL_CONFIRMED",
                "CHARGE_TOTAL_AUTHORITY",
                "CASH_RULING_PRINTED_CENTS",
            } and "CLAIM_TOTAL_CONTRADICTION" in r["claim_contradictions"]:
                raise SystemExit(
                    f"INVARIANT BROKEN: {r['claim_id']} AUTO+CONFIRMED still "
                    f"has CLAIM_TOTAL_CONTRADICTION"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
