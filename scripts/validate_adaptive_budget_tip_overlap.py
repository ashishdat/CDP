#!/usr/bin/env python3
"""Tip-overlap smoke for adaptive budget + stop ladder.

Runs cascade on a tip-cohort sample (default 20 claims from the e2e
authority TRUE_STP / HITL mix), workers=1, product residuals ON.

Gates (advisory, written to summary):
  - median elapsed ≤ 25s on first smoke (tighten to ≤20 after STP holds)
  - True STP rate within 2 pp of tip-overlap baseline on the same claim ids
  - never fold residual-off latency smoke into this gate

Usage:
  python3 scripts/validate_adaptive_budget_tip_overlap.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E_LEDGER = (
    ROOT
    / "evaluation_results"
    / "hackathon_1000_stp_recovery_e2e_authority_v1"
    / "results.jsonl"
)
OUT_DEFAULT = ROOT / "evaluation_results" / "adaptive_budget_tip_overlap_v1"


def _load_tip_claims(limit: int) -> tuple[list[str], dict[str, bool]]:
    """Prefer TRUE_STP first (stable tip), then HITL charge buckets."""
    if not E2E_LEDGER.exists():
        raise SystemExit(f"missing tip ledger: {E2E_LEDGER}")
    stp: list[str] = []
    hitl: list[str] = []
    prior: dict[str, bool] = {}
    for line in E2E_LEDGER.open():
        row = json.loads(line)
        cid = str(row.get("claim_id") or "")
        if not cid:
            continue
        is_stp = bool(row.get("true_stp"))
        prior[cid] = is_stp
        (stp if is_stp else hitl).append(cid)
    # Doc path form Group A__X → Group A/X for --documents
    def _to_doc(cid: str) -> str:
        if "__" in cid:
            group, rest = cid.split("__", 1)
            return f"{group}/{rest}"
        return cid.replace("__", "/")

    ordered = stp + hitl
    picked = ordered[: max(1, limit)]
    return [_to_doc(c) for c in picked], {c: prior[c] for c in picked}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, default=OUT_DEFAULT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print documents and exit without running cascade",
    )
    args = parser.parse_args()

    docs, prior = _load_tip_claims(args.limit)
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tip_overlap_docs.json").write_text(
        json.dumps({"documents": docs, "prior_true_stp": prior}, indent=2),
        encoding="utf-8",
    )
    if args.dry_run:
        print(json.dumps({"documents": docs, "n": len(docs)}, indent=2))
        return 0

    # Product path — never residual-off.
    env = os.environ.copy()
    env.pop("CDP_CASCADE_RESPECT_ENV", None)
    for kill in (
        "CDP_TROCR_DOB_RESIDUAL",
        "CDP_GPT4O_CROP_RESIDUAL",
        "CDP_AZURE_DI_CHARGE_RESIDUAL",
        "CDP_LEARNED_MATCHER",
        "CDP_CONFLICT_AGENT",
    ):
        env.pop(kill, None)
    env["CDP_DOC_LATENCY_BUDGET"] = "1"
    env["CDP_DOC_BUDGET_SOFT_SEC"] = "18"
    env["CDP_DOC_BUDGET_HARD_SEC"] = "22"
    env["CDP_CLOUD_STOP_LADDER"] = "1"

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_hackathon_1000_cascade.py"),
        "--out-dir",
        str(out_dir),
        "--workers",
        str(args.workers),
        "--documents",
        ",".join(docs),
        "--no-resume",
    ]
    print(f"running tip-overlap n={len(docs)} workers={args.workers}", flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if proc.returncode != 0:
        print(f"cascade exit={proc.returncode}", flush=True)
        return proc.returncode

    ledger = out_dir / "results.jsonl"
    if not ledger.exists():
        print("missing results.jsonl", flush=True)
        return 2

    rows = [json.loads(line) for line in ledger.open()]
    completed = [
        r
        for r in rows
        if str(r.get("disposition") or "") not in {"REGISTRATION_FAILED", "STAGE_FAILURE"}
    ]
    true_stp = sum(1 for r in completed if r.get("true_stp"))
    elapsed = [
        float(r.get("elapsed_sec") or r.get("latency_seconds") or 0.0)
        for r in completed
        if (r.get("elapsed_sec") or r.get("latency_seconds")) is not None
    ]
    median = statistics.median(elapsed) if elapsed else None
    rate = (true_stp / len(completed)) if completed else 0.0

    # Baseline: prior TRUE_STP rate on the same picked claim set.
    prior_stp = sum(1 for cid, ok in prior.items() if ok)
    # Map docs back: Group A/X → Group A__X
    prior_on_pick = 0
    for doc in docs:
        cid = doc.replace("/", "__", 1) if "/" in doc else doc
        if prior.get(cid):
            prior_on_pick += 1
    prior_rate = prior_on_pick / len(docs) if docs else 0.0
    delta_pp = (rate - prior_rate) * 100.0

    summary = {
        "title": "Adaptive budget tip-overlap smoke",
        "n_docs": len(docs),
        "completed": len(completed),
        "true_stp": true_stp,
        "true_stp_rate": round(rate, 5),
        "prior_true_stp_on_pick": prior_on_pick,
        "prior_true_stp_rate": round(prior_rate, 5),
        "stp_delta_pp": round(delta_pp, 3),
        "median_elapsed_sec": round(median, 3) if median is not None else None,
        "gates": {
            "median_le_25": (
                "PASS"
                if median is not None and median <= 25.0
                else "FAIL"
                if median is not None
                else "SKIP"
            ),
            "stp_within_2pp_of_prior": (
                "PASS" if delta_pp >= -2.0 else "FAIL"
            ),
        },
        "workers": args.workers,
        "hitl_attack_order": [
            "charge_field_hitl",
            "charge_conflict_margin",
            "identity_id",
            "identity_dob",
        ],
    }
    (out_dir / "tip_overlap_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    metrics = ROOT / "docs" / "metrics" / "adaptive_budget_tip_overlap_v1.json"
    metrics.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    if summary["gates"]["stp_within_2pp_of_prior"] == "FAIL":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
