"""Manifest-driven orchestration for the autonomous CDP optimizer."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evaluation.autonomous_optimizer import (
    OUTPUT_ROOT,
    AutonomousOptimizer,
    ExperimentPlan,
    Metrics,
    SafetyPolicy,
    atomic_json,
    digest,
    make_plan,
)

RUN_SCHEMA_VERSION = "autonomous-cdp-run-v1"


class ManifestMetricsRunner:
    """Replay precomputed governed observations; it never creates evidence."""

    def __init__(self, tiers: dict[str, dict[str, Any]]) -> None:
        self.tiers = tiers

    def run(self, plan: ExperimentPlan, tier: str, page_limit: int | None) -> Metrics:
        del plan, page_limit
        if tier not in self.tiers or "candidate" not in self.tiers[tier]:
            raise ValueError(f"MISSING_TIER_CANDIDATE:{tier}")
        return Metrics.from_mapping(self.tiers[tier]["candidate"])


def run_manifest(path: Path, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    manifest = json.loads(path.read_text("utf-8"))
    if manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError("INVALID_RUN_SCHEMA")
    baseline_sha = str(manifest.get("baseline_sha") or "")
    if len(baseline_sha) != 40:
        raise ValueError("INVALID_BASELINE_SHA")
    policy = SafetyPolicy(**manifest.get("safety_policy", {}))
    policy_sha256 = digest(asdict(policy))
    plan = make_plan(
        experiment_type=str(manifest.get("experiment_type")),
        cohort_key=str(manifest.get("cohort_key") or ""),
        change=dict(manifest.get("change") or {}),
        baseline_sha=baseline_sha,
        policy_sha256=policy_sha256,
    )
    tiers = manifest.get("tiers")
    if not isinstance(tiers, dict):
        raise ValueError("MISSING_TIER_EVIDENCE")
    experiment_dir = output_root / plan.experiment_id
    optimizer = AutonomousOptimizer(experiment_dir, baseline_sha, policy)
    runner = ManifestMetricsRunner(tiers)
    decisions: dict[str, Any] = {}
    for tier in ("A", "B", "C"):
        prior = optimizer.state.completed_tiers.get(tier)
        if prior is not None:
            decisions[tier] = {"verdict": prior, "resumed": True}
            if prior != "PASS":
                break
            continue
        tier_payload = tiers.get(tier)
        if not isinstance(tier_payload, dict) or "baseline" not in tier_payload:
            raise ValueError(f"MISSING_TIER_BASELINE:{tier}")
        baseline = Metrics.from_mapping(tier_payload["baseline"])
        decision = optimizer.execute_tier(plan, tier, baseline, runner)
        decisions[tier] = asdict(decision)
        if decision.verdict != "PASS":
            break
    if all(decisions.get(tier, {}).get("verdict") == "PASS" for tier in ("A", "B", "C")):
        qualification = optimizer.qualify(plan)
        status = "QUALIFIED"
    else:
        qualification = None
        status = "REVERTED"
    report = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": status,
        "experiment_id": plan.experiment_id,
        "baseline_sha": baseline_sha,
        "policy_sha256": policy_sha256,
        "decisions": decisions,
        "qualification": qualification,
    }
    report["report_sha256"] = digest(report)
    atomic_json(experiment_dir / "run_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    report = run_manifest(args.manifest, args.output_root)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
