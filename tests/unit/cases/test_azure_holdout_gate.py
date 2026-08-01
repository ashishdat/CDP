import copy

from evaluation.azure_holdout_gate import calculate_gate

POLICY = {
    "holdout": {"minimum_eligible_fields": 300},
    "promotion_gate": {
        "selective_accuracy_minimum": 0.99,
        "critical_false_accepts_maximum": 0,
        "invalid_crop_abstention_minimum": 1.0,
        "provenance_completeness_minimum": 1.0,
        "leakage_violations_maximum": 0,
        "incremental_recovery_minimum_exclusive": 0,
        "extraction_v2_regressions_maximum": 0,
    },
    "rollout": {"initial_canary_fraction": 0.05, "immediate_rollback_required": True},
}


def _row():
    return {
        "azure_selected": True, "azure_correct": True, "azure_abstained": False,
        "should_abstain": False, "crop_condition": "VALID",
        "criticality": "NONCRITICAL", "ocr_correct": False,
        "review_avoided": True, "azure_cost_usd": 0.004,
        "provenance_complete": True, "leakage_violation": False,
        "v2_regression": False, "new_document": True,
        "inference_before_labeling": True, "azure_confident": True,
        "azure_latency_ms": 500,
    }


def test_nine_shadow_examples_cannot_pass_holdout_gate():
    rows = [_row() for _ in range(9)]
    assert calculate_gate(rows, POLICY, reviewer_cost=0.75)["passed"] is False


def test_qualified_300_field_holdout_can_pass_route_gate():
    rows = [_row() for _ in range(300)]
    for index in range(30):
        rows[index] = copy.deepcopy(rows[index])
        rows[index].update({
            "azure_selected": False, "azure_correct": False,
            "azure_abstained": True, "should_abstain": True,
            "crop_condition": "INVALID", "review_avoided": False,
            "azure_confident": False,
        })
    report = calculate_gate(rows, POLICY, reviewer_cost=0.75)
    assert report["passed"] is True
    assert report["canary_fraction"] == 0.05
