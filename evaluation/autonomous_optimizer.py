"""Governed, evaluation-only autonomous CDP optimization harness.

The harness proposes and evaluates bounded configuration experiments. It cannot
change runtime policy, acceptance thresholds, frozen truth, or OCR evidence. A
candidate reaches ``QUALIFIED`` only after ordered A/B/C replay tiers and every
safety invariant passes against the same cohort and denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "evaluation_results" / "autonomous_optimizer"
HARNESS_VERSION = "autonomous-cdp-optimizer-v1"
SCHEMA_VERSION = "autonomous-cdp-experiment-v1"
TIER_LIMITS: dict[str, int | None] = {"A": 100, "B": 500, "C": None}
TIER_PREDECESSOR = {"A": None, "B": "A", "C": "B"}
ALLOWED_EXPERIMENT_TYPES = frozenset(
    {
        "PREPROCESSING_PROFILE",
        "LOCALIZATION_REGION",
        "FIELD_ROUTE_ORDER",
        "CHALLENGER_ELIGIBILITY",
        "DETERMINISTIC_NORMALIZATION",
    }
)
FORBIDDEN_MUTATION_KEYS = frozenset(
    {
        "acceptance_threshold",
        "ground_truth",
        "criticality",
        "identity_policy",
        "evidence_policy",
        "llm_acceptance",
        "frozen_input",
    }
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    data = value if isinstance(value, bytes) else canonical_bytes(value)
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class SafetyPolicy:
    """Immutable promotion requirements; callers cannot weaken these floors."""

    maximum_critical_false_accepts: int = 0
    minimum_accepted_precision_delta: float = 0.0
    minimum_source_accuracy_delta: float = 0.0
    maximum_hitl_rate_delta: float = 0.0
    maximum_latency_ratio: float = 1.10
    maximum_cost_ratio: float = 1.10

    def __post_init__(self) -> None:
        if self.maximum_critical_false_accepts != 0:
            raise ValueError("critical false accepts must remain zero")
        if self.minimum_accepted_precision_delta < 0:
            raise ValueError("accepted precision may not be degraded")
        if self.minimum_source_accuracy_delta < 0:
            raise ValueError("accuracy delta may not be negative")
        if self.maximum_hitl_rate_delta > 0:
            raise ValueError("HITL rate may not increase")
        if self.maximum_latency_ratio < 1 or self.maximum_cost_ratio < 1:
            raise ValueError("latency and cost ratios must be at least one")


@dataclass(frozen=True)
class Metrics:
    evaluated_pages: int
    accepted_precision: float
    source_accuracy: float
    hitl_rate: float
    critical_false_accepts: int
    latency_ms_per_page: float
    cost_usd_per_page: float
    cohort_sha256: str
    truth_sha256: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Metrics:
        required = set(cls.__dataclass_fields__)
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"METRICS_INCOMPLETE:{','.join(missing)}")
        result = cls(**{name: value[name] for name in required})
        if result.evaluated_pages <= 0:
            raise ValueError("EMPTY_EVALUATION_COHORT")
        for name in ("accepted_precision", "source_accuracy", "hitl_rate"):
            if not 0 <= getattr(result, name) <= 1:
                raise ValueError(f"INVALID_RATE:{name}")
        if not result.cohort_sha256 or not result.truth_sha256:
            raise ValueError("MISSING_EVALUATION_PROVENANCE")
        return result


@dataclass(frozen=True)
class ExperimentPlan:
    experiment_id: str
    experiment_type: str
    cohort_key: str
    change: dict[str, Any]
    baseline_sha: str
    policy_sha256: str
    created_at: str
    evaluation_only: bool = True


@dataclass(frozen=True)
class GateDecision:
    verdict: str
    reasons: tuple[str, ...]
    deltas: dict[str, float]


@dataclass
class OptimizerState:
    baseline_sha: str
    policy_sha256: str
    completed_tiers: dict[str, str] = field(default_factory=dict)
    status: str = "PLANNED"
    history: list[dict[str, Any]] = field(default_factory=list)


class ExperimentRunner(Protocol):
    def run(self, plan: ExperimentPlan, tier: str, page_limit: int | None) -> Metrics: ...


def profile_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate unresolved observations into actionable, claim-aware cohorts."""
    counts: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    claims: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for row in rows:
        if row.get("accepted") is True and row.get("hitl") is not True:
            continue
        key = tuple(
            str(row.get(name) or "UNKNOWN")
            for name in ("source", "quality_band", "field_name", "failure_reason", "ocr_engine")
        )
        counts[key]["blockers"] += 1
        if row.get("claim_id"):
            claims[key].add(str(row["claim_id"]))
        if row.get("sole_claim_blocker") is True:
            counts[key]["unlockable_claims"] += 1
        if row.get("critical") is True:
            counts[key]["critical_blockers"] += 1
    result = []
    for key in sorted(counts):
        source, quality, field_name, reason, engine = key
        counter = counts[key]
        result.append(
            {
                "cohort_key": "/".join(key),
                "source": source,
                "quality_band": quality,
                "field_name": field_name,
                "failure_reason": reason,
                "ocr_engine": engine,
                "blockers": counter["blockers"],
                "claims_affected": len(claims[key]),
                "unlockable_claims": counter["unlockable_claims"],
                "critical_blockers": counter["critical_blockers"],
            }
        )
    return result


def prioritize_cohorts(cohorts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank by safe claim-unlock value, then size, with critical cohorts later."""
    return sorted(
        cohorts,
        key=lambda row: (
            -int(row["unlockable_claims"]),
            -int(row["blockers"]),
            int(row["critical_blockers"]),
            str(row["cohort_key"]),
        ),
    )


def make_plan(
    *,
    experiment_type: str,
    cohort_key: str,
    change: dict[str, Any],
    baseline_sha: str,
    policy_sha256: str,
) -> ExperimentPlan:
    if experiment_type not in ALLOWED_EXPERIMENT_TYPES:
        raise ValueError("EXPERIMENT_TYPE_NOT_ALLOWED")
    forbidden = sorted(FORBIDDEN_MUTATION_KEYS.intersection(change))
    if forbidden:
        raise ValueError(f"FORBIDDEN_MUTATION:{','.join(forbidden)}")
    body = {
        "schema_version": SCHEMA_VERSION,
        "experiment_type": experiment_type,
        "cohort_key": cohort_key,
        "change": change,
        "baseline_sha": baseline_sha,
        "policy_sha256": policy_sha256,
    }
    return ExperimentPlan(
        experiment_id=digest(body)[:24],
        experiment_type=experiment_type,
        cohort_key=cohort_key,
        change=change,
        baseline_sha=baseline_sha,
        policy_sha256=policy_sha256,
        created_at=datetime.now(UTC).isoformat(),
    )


def safety_gate(baseline: Metrics, candidate: Metrics, policy: SafetyPolicy) -> GateDecision:
    reasons: list[str] = []
    if candidate.cohort_sha256 != baseline.cohort_sha256:
        reasons.append("COHORT_MISMATCH")
    if candidate.truth_sha256 != baseline.truth_sha256:
        reasons.append("TRUTH_MISMATCH")
    if candidate.evaluated_pages != baseline.evaluated_pages:
        reasons.append("DENOMINATOR_MISMATCH")
    if candidate.critical_false_accepts > policy.maximum_critical_false_accepts:
        reasons.append("CRITICAL_FALSE_ACCEPT")
    precision_delta = candidate.accepted_precision - baseline.accepted_precision
    accuracy_delta = candidate.source_accuracy - baseline.source_accuracy
    hitl_delta = candidate.hitl_rate - baseline.hitl_rate
    latency_ratio = candidate.latency_ms_per_page / max(baseline.latency_ms_per_page, 1e-12)
    cost_ratio = candidate.cost_usd_per_page / max(baseline.cost_usd_per_page, 1e-12)
    if precision_delta < policy.minimum_accepted_precision_delta:
        reasons.append("ACCEPTED_PRECISION_REGRESSION")
    if accuracy_delta < policy.minimum_source_accuracy_delta:
        reasons.append("SOURCE_ACCURACY_REGRESSION")
    if hitl_delta > policy.maximum_hitl_rate_delta:
        reasons.append("HITL_REGRESSION")
    if latency_ratio > policy.maximum_latency_ratio:
        reasons.append("LATENCY_BUDGET_EXCEEDED")
    if cost_ratio > policy.maximum_cost_ratio:
        reasons.append("COST_BUDGET_EXCEEDED")
    return GateDecision(
        "PASS" if not reasons else "FAIL",
        tuple(reasons),
        {
            "accepted_precision": precision_delta,
            "source_accuracy": accuracy_delta,
            "hitl_rate": hitl_delta,
            "latency_ratio": latency_ratio,
            "cost_ratio": cost_ratio,
        },
    )


class AutonomousOptimizer:
    """Execute ordered tiers with hash-bound checkpoints and safe reversion."""

    def __init__(
        self, output_dir: Path, baseline_sha: str, policy: SafetyPolicy | None = None
    ) -> None:
        self.output_dir = output_dir
        self.policy = policy or SafetyPolicy()
        self.policy_sha256 = digest(asdict(self.policy))
        self.state_path = output_dir / "optimizer_state.json"
        self.state = OptimizerState(baseline_sha, self.policy_sha256)
        if self.state_path.exists():
            raw = json.loads(self.state_path.read_text("utf-8"))
            stored_hash = raw.pop("record_sha256", None)
            if stored_hash != digest(raw):
                raise ValueError("TAMPERED_OPTIMIZER_STATE")
            restored = OptimizerState(**raw)
            if restored.baseline_sha != baseline_sha:
                raise ValueError("STALE_BASELINE_STATE")
            if restored.policy_sha256 != self.policy_sha256:
                raise ValueError("STALE_POLICY_STATE")
            self.state = restored

    def _save(self) -> None:
        payload = asdict(self.state)
        payload["record_sha256"] = digest(payload)
        atomic_json(self.state_path, payload)

    def execute_tier(
        self,
        plan: ExperimentPlan,
        tier: str,
        baseline: Metrics,
        runner: ExperimentRunner,
    ) -> GateDecision:
        if tier not in TIER_LIMITS:
            raise ValueError("UNKNOWN_EXPERIMENT_TIER")
        if plan.baseline_sha != self.state.baseline_sha:
            raise ValueError("PLAN_BASELINE_MISMATCH")
        if plan.policy_sha256 != self.policy_sha256:
            raise ValueError("PLAN_POLICY_MISMATCH")
        predecessor = TIER_PREDECESSOR[tier]
        if predecessor and self.state.completed_tiers.get(predecessor) != "PASS":
            raise ValueError("TIER_PREDECESSOR_NOT_PASSED")
        if tier in self.state.completed_tiers:
            raise ValueError("TIER_ALREADY_COMPLETED")
        page_limit = TIER_LIMITS[tier]
        candidate = runner.run(plan, tier, page_limit)
        if page_limit is not None and candidate.evaluated_pages > page_limit:
            raise ValueError("TIER_PAGE_LIMIT_EXCEEDED")
        decision = safety_gate(baseline, candidate, self.policy)
        record = {
            "schema_version": SCHEMA_VERSION,
            "harness_version": HARNESS_VERSION,
            "experiment_id": plan.experiment_id,
            "tier": tier,
            "page_limit": page_limit,
            "baseline": asdict(baseline),
            "candidate": asdict(candidate),
            "decision": asdict(decision),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
        record["record_sha256"] = digest(record)
        atomic_json(self.output_dir / plan.experiment_id / f"tier_{tier}.json", record)
        self.state.completed_tiers[tier] = decision.verdict
        self.state.status = "REVERTED" if decision.verdict == "FAIL" else f"TIER_{tier}_PASSED"
        self.state.history.append(
            {"experiment_id": plan.experiment_id, "tier": tier, "verdict": decision.verdict}
        )
        self._save()
        return decision

    def qualify(self, plan: ExperimentPlan) -> dict[str, Any]:
        if any(self.state.completed_tiers.get(tier) != "PASS" for tier in TIER_LIMITS):
            raise ValueError("FULL_QUALIFICATION_INCOMPLETE")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "harness_version": HARNESS_VERSION,
            "status": "QUALIFIED_EVALUATION_CANDIDATE",
            "runtime_activation": False,
            "requires_independent_release_approval": True,
            "baseline_sha": self.state.baseline_sha,
            "policy_sha256": self.policy_sha256,
            "experiment": asdict(plan),
            "completed_tiers": dict(self.state.completed_tiers),
        }
        manifest["manifest_sha256"] = digest(manifest)
        atomic_json(self.output_dir / plan.experiment_id / "qualification.json", manifest)
        self.state.status = "QUALIFIED"
        self._save()
        return manifest


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _version(distribution: str, configured: str) -> dict[str, str]:
    try:
        installed = metadata.version(distribution)
    except metadata.PackageNotFoundError:
        installed = "NOT_INSTALLED"
    return {"configured": configured, "installed": installed}


def build_github_baseline(test_results: dict[str, Any]) -> dict[str, Any]:
    from evaluation.strict_identity_cached_replay import decision_policy_manifest

    routing = decision_policy_manifest()
    payload = {
        "schema_version": "autonomous-cdp-github-baseline-v1",
        "repository": "ashishdat/CDP",
        "remote_url": _git("remote", "get-url", "origin"),
        "selected_base_branch": "origin/fix/strict-claim-form-identity-gate",
        "baseline_sha": _git("rev-parse", "HEAD"),
        "commit_timestamp": _git("show", "-s", "--format=%cI", "HEAD"),
        "pipeline_version": HARNESS_VERSION,
        "ocr_engines": {
            "rapidocr-onnxruntime": _version("rapidocr-onnxruntime", ">=1.3,<2"),
            "paddleocr_primary": _version("paddleocr", ">=2.7,<3"),
            "ppocr_v5_challenger": _version("paddleocr", ">=3,<4 (isolated image)"),
        },
        "identity_policy_version": routing["identity_policy_version"],
        "identity_policy_sha256": routing["decision_policy_sha256"],
        "evidence_policy_version": "claim-evidence-v1",
        "acceptance_policy_version": "production-promotion-gate-v1.0",
        "azure_adjudication_configuration_version": "azure-openai-closed-world-v1",
        "test_results": test_results,
    }
    payload["baseline_manifest_sha256"] = digest(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze-baseline")
    freeze.add_argument("--test-results", type=Path, required=True)
    freeze.add_argument("--output", type=Path, default=OUTPUT_ROOT / "github_baseline.json")
    profile = subparsers.add_parser("profile")
    profile.add_argument("--rows", type=Path, required=True)
    profile.add_argument("--output", type=Path, default=OUTPUT_ROOT / "failure_cohorts.json")
    args = parser.parse_args()
    if args.command == "freeze-baseline":
        tests = json.loads(args.test_results.read_text("utf-8"))
        atomic_json(args.output, build_github_baseline(tests))
    else:
        rows = json.loads(args.rows.read_text("utf-8"))
        result = prioritize_cohorts(profile_failures(rows))
        payload = {"schema_version": SCHEMA_VERSION, "cohorts": result}
        payload["profile_sha256"] = digest(payload)
        atomic_json(args.output, payload)


if __name__ == "__main__":
    main()
