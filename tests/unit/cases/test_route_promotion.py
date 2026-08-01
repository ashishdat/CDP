from packages.route_promotion import (
    RouteMetrics,
    RouteStatus,
    next_canary_status,
    promotion_eligible,
    should_rollback,
)


def test_route_gate_and_canary_are_field_scoped():
    metrics = RouteMetrics(300, .995, 0, 1.0, 1.0, 2, 0, .05, .75)
    assert promotion_eligible(metrics)
    assert next_canary_status(RouteStatus.ELIGIBLE, healthy=True) == RouteStatus.CANARY_5


def test_any_safety_failure_rolls_back():
    assert should_rollback(
        critical_false_accepts=1, selective_accuracy=1.0,
        crop_quality_drift=False, unknown_form_version=False,
        schema_failure=False, over_budget=False, reference_contradiction=False,
    )
    assert next_canary_status(RouteStatus.CANARY_25, healthy=False) == RouteStatus.ROLLED_BACK
