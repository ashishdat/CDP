"""Field/family-scoped promotion and fail-closed canary policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RouteStatus(StrEnum):
    BLOCKED = "BLOCKED"
    ELIGIBLE = "ELIGIBLE"
    CANARY_5 = "CANARY_5"
    CANARY_25 = "CANARY_25"
    CANARY_50 = "CANARY_50"
    ACTIVE = "ACTIVE"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True)
class RouteMetrics:
    eligible_fields: int
    selective_accuracy: float
    critical_false_accepts: int
    invalid_crop_abstention: float
    provenance_completeness: float
    incremental_recovery: int
    baseline_regressions: int
    cost_per_avoided_review: float
    reviewer_cost: float


def promotion_eligible(metrics: RouteMetrics) -> bool:
    return (
        metrics.eligible_fields >= 300
        and metrics.selective_accuracy >= 0.99
        and metrics.critical_false_accepts == 0
        and metrics.invalid_crop_abstention == 1.0
        and metrics.provenance_completeness == 1.0
        and metrics.incremental_recovery > 0
        and metrics.baseline_regressions == 0
        and metrics.cost_per_avoided_review < metrics.reviewer_cost
    )


def should_rollback(*, critical_false_accepts: int, selective_accuracy: float,
                    crop_quality_drift: bool, unknown_form_version: bool,
                    schema_failure: bool, over_budget: bool,
                    reference_contradiction: bool) -> bool:
    return any((
        critical_false_accepts > 0,
        selective_accuracy < 0.99,
        crop_quality_drift,
        unknown_form_version,
        schema_failure,
        over_budget,
        reference_contradiction,
    ))


def next_canary_status(current: RouteStatus, *, healthy: bool) -> RouteStatus:
    if not healthy:
        return RouteStatus.ROLLED_BACK
    return {
        RouteStatus.ELIGIBLE: RouteStatus.CANARY_5,
        RouteStatus.CANARY_5: RouteStatus.CANARY_25,
        RouteStatus.CANARY_25: RouteStatus.CANARY_50,
        RouteStatus.CANARY_50: RouteStatus.ACTIVE,
    }.get(current, current)
