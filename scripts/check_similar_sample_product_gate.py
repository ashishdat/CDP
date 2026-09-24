#!/usr/bin/env python3
"""Enforce similar-sample product gate: ≥97% claim-page STP · FA=0.

Design: docs/PRODUCT_STP_ACCURACY_APPLICATION_V1.md
Contract: config/product_stp_accuracy_contract_v1.yaml
Profiles: config/run_profiles_v1.yaml (PRODUCT required; FAST refused)

Usage:
  python3 -u scripts/check_similar_sample_product_gate.py \\
    --ledger-a evaluation_results/hackathon_600_independent_v13c \\
    --ledger-b evaluation_results/hackathon_400_remainder_independent_v13c \\
    --write docs/metrics/similar_sample_product_gate_latest.json

  # Develop without agent GT present:
  python3 -u scripts/check_similar_sample_product_gate.py ... --allow-incomplete-gt

  # Tip-seed replay only (not live proof on a new corpus):
  python3 -u scripts/check_similar_sample_product_gate.py ... --allow-tip-seed
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
from packages.run_profiles.profiles import read_run_manifest  # noqa: E402


def _latest(ledger: Path) -> dict[str, dict]:
    by: dict[str, dict] = {}
    if not ledger.is_file():
        return by
    for line in ledger.open(encoding="utf-8"):
        row = json.loads(line)
        by[row["claim_id"]] = row
    return by


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    parser.add_argument(
        "--allow-tip-seed",
        action="store_true",
        help="Allow TIP_SEED manifests (historical tip replay only)",
    )
    parser.add_argument(
        "--allow-missing-manifest",
        action="store_true",
        help="Allow ledgers without run_manifest.json (legacy migration only)",
    )
    parser.add_argument(
        "--allow-fast",
        action="store_true",
        help="Debug only: score a FAST ledger (will not claim product PASS honestly)",
    )
    args = parser.parse_args()

    allow_incomplete = args.allow_incomplete_gt or _env_flag(
        "CDP_PRODUCT_GATE_ALLOW_INCOMPLETE_GT"
    )
    allow_tip = args.allow_tip_seed or _env_flag("CDP_PRODUCT_GATE_ALLOW_TIP_SEED")
    allow_missing = args.allow_missing_manifest or _env_flag(
        "CDP_PRODUCT_GATE_ALLOW_MISSING_MANIFEST"
    )
    allow_fast = args.allow_fast or _env_flag("CDP_PRODUCT_GATE_ALLOW_FAST")

    merged: dict[str, dict] = {}
    manifests: list[dict] = []
    for raw in (args.ledger_a, args.ledger_b):
        if raw is None:
            continue
        root = raw if raw.is_absolute() else ROOT / raw
        merged.update(_latest(root / "results.jsonl"))
        man = read_run_manifest(root)
        if man is not None:
            manifests.append(man)

    if not merged:
        print("ERROR: empty ledger merge", file=sys.stderr)
        return 2

    # Prefer the most restrictive / first manifest; if any is FAST, gate sees FAST.
    run_manifest = None
    if manifests:
        by_profile = {str(m.get("profile") or "").upper(): m for m in manifests}
        if "FAST" in by_profile:
            run_manifest = by_profile["FAST"]
        elif "MIXED" in by_profile:
            run_manifest = by_profile["MIXED"]
        elif "PRODUCT" in by_profile:
            run_manifest = by_profile["PRODUCT"]
        else:
            run_manifest = manifests[0]

    contract = load_product_contract(str(args.contract) if args.contract else None)
    result = evaluate_similar_sample_gate(
        merged,
        contract=contract,
        allow_incomplete_gt=allow_incomplete,
        run_manifest=run_manifest,
        allow_tip_seed=allow_tip,
        allow_missing_manifest=allow_missing,
        allow_fast=allow_fast,
    )
    payload = {
        **result.to_dict(),
        "n": len(merged),
        "contract_version": contract.get("version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "allow_incomplete_gt": allow_incomplete,
        "run_manifest": run_manifest,
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
