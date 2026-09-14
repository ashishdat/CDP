from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .diagnosis import Cause, Diagnosis


class Strategy(StrEnum):
    IMAGE_ENHANCEMENT = "IMAGE_ENHANCEMENT"
    ALTERNATIVE_TEMPLATE = "ALTERNATIVE_TEMPLATE"
    REFERENCE_RECOVERY = "REFERENCE_RECOVERY"
    ALTERNATIVE_REGISTRATION = "ALTERNATIVE_REGISTRATION"
    ALTERNATIVE_OCR = "ALTERNATIVE_OCR"
    HUMAN_QUEUE = "HUMAN_QUEUE"
    NONE = "NONE"


@dataclass(frozen=True)
class RecoveryPlan:
    strategy: Strategy
    cause: Cause
    executable: bool
    reason: str
    max_attempts: int = 0


def plan_recovery(diagnosis: Diagnosis, *, strategy_available: bool = False) -> RecoveryPlan:
    """Return at most one bounded strategy; never produce a blind retry."""
    mapping = {
        Cause.POOR_SCAN: Strategy.IMAGE_ENHANCEMENT,
        Cause.WRONG_TEMPLATE: Strategy.ALTERNATIVE_TEMPLATE,
        Cause.TEMPLATE_EVOLUTION: Strategy.ALTERNATIVE_TEMPLATE,
        Cause.MISSING_ASSET: Strategy.REFERENCE_RECOVERY,
        Cause.REGISTRATION_FAILURE: Strategy.ALTERNATIVE_REGISTRATION,
        Cause.OCR_FAILURE: Strategy.ALTERNATIVE_OCR,
        Cause.UNKNOWN_DOCUMENT: Strategy.HUMAN_QUEUE,
        Cause.UNSUPPORTED_FORM: Strategy.HUMAN_QUEUE,
        Cause.CONTRACT_FAILURE: Strategy.NONE,
        Cause.UNDETERMINED: Strategy.HUMAN_QUEUE,
    }
    strategy = mapping[diagnosis.primary_cause]
    if strategy is Strategy.NONE:
        return RecoveryPlan(strategy, diagnosis.primary_cause, False, "Restore the artifact contract before recovery")
    if strategy is Strategy.HUMAN_QUEUE:
        return RecoveryPlan(strategy, diagnosis.primary_cause, False, "Queue for human resolution; no automated retry")
    if diagnosis.confidence in {"INSUFFICIENT_EVIDENCE", "LOW"}:
        return RecoveryPlan(Strategy.HUMAN_QUEUE, diagnosis.primary_cause, False, "Diagnosis is insufficient for automated recovery")
    if not strategy_available:
        return RecoveryPlan(strategy, diagnosis.primary_cause, False, "Approved strategy is unavailable")
    return RecoveryPlan(strategy, diagnosis.primary_cause, True, "One cause-specific attempt permitted", max_attempts=1)
