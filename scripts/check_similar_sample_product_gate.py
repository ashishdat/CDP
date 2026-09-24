#!/usr/bin/env python3
"""Enforce similar-sample product gate: ≥97% claim-page STP · FA=0.

Design: docs/PRODUCT_STP_ACCURACY_APPLICATION_V1.md
Contract: config/product_stp_accuracy_contract_v1.yaml

Usage:
  python3 -u scripts/check_similar_sample_product_gate.py \\
    --ledger-a evaluation_results/hackathon_600_independent_v13c \\
    --ledger-b evaluation_results/hackathon_400_remainder_independent_v13c \\
    --write docs/metrics/similar_sample_product_gate_latest.json

  # Develop without agent GT present:
  python3 -u scripts/check_similar_sample_product_gate.py ... --allow-incomplete-gt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.product_gates.similar_sample_gate import (  # noqa: E402
    evaluate_similar_sample_gate,
    load_product_contract,
)


def _latest(ledger: Path) -> dict[str, dict]:
    by: dict[str, dict] = {}
    if not ledger.is_file():
        return by
    for line in ledger.open(encoding="utf-8"):
        row = json.loads(line)
        by[row["claim_id"]] = row
    return by


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-a", type=Path, required=True)
    parser.add_argument("--ledger-b", type=Path, default=None)
    parser.add_argument("--contract", type=Path, default=None)
    parser.add_argument("--write", type=Path, default=None)
    parser.add_argument(
        "--allow-incomplete-gt",
        action="store_true",
        help="Pass FA side when agent GT is missing (dev only)",
    )
    args = parser.parse_args()

    env_allow = (os.environ.get("CDP_PRODUCT_GATE_ALLOW_INCOMPLETE_GT") or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    allow_incomplete = args.allow_incomplete_gt or env_allow

    merged: dict[str, dict] = {}
    for raw in (args.ledger_a, args.ledger_b):
        if raw is None:
            continue
        root = raw if raw.is_absolute() else ROOT / raw
        merged.update(_latest(root / "results.jsonl"))

    if not merged:
        print("ERROR: empty ledger merge", file=sys.stderr)
        return 2

    contract = load_product_contract(str(args.contract) if args.contract else None)
    result = evaluate_similar_sample_gate(
        merged,
        contract=contract,
        allow_incomplete_gt=allow_incomplete,
    )
    payload = {
        **result.to_dict(),
        "n": len(merged),
        "contract_version": contract.get("version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "allow_incomplete_gt": allow_incomplete,
    }
    print(json.dumps(payload, indent=2))
    if args.write:
        out = args.write if args.write.is_absolute() else ROOT / args.write
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0 if result.pass_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
