from dataclasses import replace

import pytest

from evaluation.autonomous_optimizer import (
    AutonomousOptimizer,
    Metrics,
    SafetyPolicy,
    make_plan,
    prioritize_cohorts,
    profile_failures,
    safety_gate,
)


def metrics(**overrides):
    values = {
        "evaluated_pages": 100,
        "accepted_precision": 0.99,
        "source_accuracy": 0.90,
        "hitl_rate": 0.20,
        "critical_false_accepts": 0,
        "latency_ms_per_page": 100.0,
        "cost_usd_per_page": 0.01,
        "cohort_sha256": "cohort",
        "truth_sha256": "truth",
    }
    values.update(overrides)
    return Metrics.from_mapping(values)


class Runner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, plan, tier, page_limit):
        self.calls.append((plan.experiment_id, tier, page_limit))
        return self.result


def plan(optimizer, change=None):
    return make_plan(
        experiment_type="LOCALIZATION_REGION",
        cohort_key="B/LOW/patient_name/MISSING/rapidocr",
        change=change or {"padding_px": 4},
        baseline_sha="a" * 40,
        policy_sha256=optimizer.policy_sha256,
    )


def test_failure_profiler_prioritizes_claim_unlock():
    rows = [
        {"claim_id": "c1", "source": "B", "quality_band": "LOW", "field_name": "npi",
         "failure_reason": "INVALID", "ocr_engine": "rapidocr", "hitl": True,
         "sole_claim_blocker": False, "critical": True},
        {"claim_id": "c2", "source": "B", "quality_band": "HIGH", "field_name": "name",
         "failure_reason": "MISSING", "ocr_engine": "rapidocr", "hitl": True,
         "sole_claim_blocker": True, "critical": False},
        {"claim_id": "c3", "accepted": True, "hitl": False},
    ]
    ranked = prioritize_cohorts(profile_failures(rows))
    assert ranked[0]["field_name"] == "name"
    assert ranked[0]["unlockable_claims"] == 1
    assert sum(row["blockers"] for row in ranked) == 2


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"critical_false_accepts": 1}, "CRITICAL_FALSE_ACCEPT"),
        ({"accepted_precision": 0.98}, "ACCEPTED_PRECISION_REGRESSION"),
        ({"source_accuracy": 0.89}, "SOURCE_ACCURACY_REGRESSION"),
        ({"hitl_rate": 0.21}, "HITL_REGRESSION"),
        ({"latency_ms_per_page": 111.0}, "LATENCY_BUDGET_EXCEEDED"),
        ({"cost_usd_per_page": 0.0111}, "COST_BUDGET_EXCEEDED"),
        ({"cohort_sha256": "other"}, "COHORT_MISMATCH"),
        ({"truth_sha256": "other"}, "TRUTH_MISMATCH"),
        ({"evaluated_pages": 99}, "DENOMINATOR_MISMATCH"),
    ],
)
def test_safety_gate_fails_closed_for_regressions(changes, reason):
    base = metrics()
    decision = safety_gate(base, replace(base, **changes), SafetyPolicy())
    assert decision.verdict == "FAIL"
    assert reason in decision.reasons


def test_safety_policy_cannot_relax_core_gates():
    with pytest.raises(ValueError, match="critical false accepts"):
        SafetyPolicy(maximum_critical_false_accepts=1)
    with pytest.raises(ValueError, match="precision"):
        SafetyPolicy(minimum_accepted_precision_delta=-0.01)
    with pytest.raises(ValueError, match="HITL"):
        SafetyPolicy(maximum_hitl_rate_delta=0.01)


def test_planner_rejects_truth_threshold_and_llm_acceptance_mutations(tmp_path):
    optimizer = AutonomousOptimizer(tmp_path, "a" * 40)
    for key in ("acceptance_threshold", "ground_truth", "llm_acceptance"):
        with pytest.raises(ValueError, match="FORBIDDEN_MUTATION"):
            plan(optimizer, {key: "changed"})
    with pytest.raises(ValueError, match="EXPERIMENT_TYPE_NOT_ALLOWED"):
        make_plan(experiment_type="NEW_OCR_ENGINE", cohort_key="x", change={},
                  baseline_sha="a" * 40, policy_sha256=optimizer.policy_sha256)


def test_tiers_are_ordered_bounded_and_not_runtime_authority(tmp_path):
    optimizer = AutonomousOptimizer(tmp_path, "a" * 40)
    experiment = plan(optimizer)
    runner = Runner(metrics())
    with pytest.raises(ValueError, match="PREDECESSOR"):
        optimizer.execute_tier(experiment, "B", metrics(), runner)
    assert optimizer.execute_tier(experiment, "A", metrics(), runner).verdict == "PASS"
    assert runner.calls[-1][2] == 100
    assert optimizer.execute_tier(experiment, "B", metrics(), runner).verdict == "PASS"
    assert runner.calls[-1][2] == 500
    assert optimizer.execute_tier(experiment, "C", metrics(), runner).verdict == "PASS"
    assert runner.calls[-1][2] is None
    qualification = optimizer.qualify(experiment)
    assert qualification["runtime_activation"] is False
    assert qualification["requires_independent_release_approval"] is True


def test_failed_tier_reverts_and_blocks_escalation(tmp_path):
    optimizer = AutonomousOptimizer(tmp_path, "a" * 40)
    experiment = plan(optimizer)
    assert optimizer.execute_tier(
        experiment, "A", metrics(), Runner(metrics(critical_false_accepts=1))
    ).verdict == "FAIL"
    assert optimizer.state.status == "REVERTED"
    with pytest.raises(ValueError, match="PREDECESSOR"):
        optimizer.execute_tier(experiment, "B", metrics(), Runner(metrics()))
    with pytest.raises(ValueError, match="FULL_QUALIFICATION_INCOMPLETE"):
        optimizer.qualify(experiment)


def test_tier_limit_and_stale_plan_fail_closed(tmp_path):
    optimizer = AutonomousOptimizer(tmp_path, "a" * 40)
    experiment = plan(optimizer)
    with pytest.raises(ValueError, match="TIER_PAGE_LIMIT_EXCEEDED"):
        optimizer.execute_tier(
            experiment, "A", metrics(evaluated_pages=101), Runner(metrics(evaluated_pages=101))
        )
    stale = replace(experiment, baseline_sha="b" * 40)
    with pytest.raises(ValueError, match="PLAN_BASELINE_MISMATCH"):
        AutonomousOptimizer(tmp_path / "stale", "a" * 40).execute_tier(
            stale, "A", metrics(), Runner(metrics())
        )


def test_checkpoint_tampering_is_detected(tmp_path):
    optimizer = AutonomousOptimizer(tmp_path, "a" * 40)
    optimizer.execute_tier(plan(optimizer), "A", metrics(), Runner(metrics()))
    state_path = tmp_path / "optimizer_state.json"
    state = __import__("json").loads(state_path.read_text("utf-8"))
    state["status"] = "QUALIFIED"
    state_path.write_text(__import__("json").dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="TAMPERED_OPTIMIZER_STATE"):
        AutonomousOptimizer(tmp_path, "a" * 40)
