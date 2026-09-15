"""Cause-driven recovery planning primitives.

These primitives decide whether a failed extraction has enough evidence for a
single bounded recovery strategy. They do not invent geometry or alter V1
algorithms beyond the authorized enhancement retry.
"""

from .diagnosis import Cause, Diagnosis, diagnose
from .ocr_recovery import OcrRecoveryDecision, decide_ocr_recovery
from .planner import RecoveryPlan, Strategy, plan_recovery
from .registration_content import ContentValidationResult, validate_cms1500_registration_content
from .registration_recovery import (
    RegistrationRecoveryDecision,
    decide_registration_recovery,
    enhance_for_registration,
    evidence_grade_alignment_confidence,
)

__all__ = [
    "Cause",
    "ContentValidationResult",
    "Diagnosis",
    "OcrRecoveryDecision",
    "RecoveryPlan",
    "RegistrationRecoveryDecision",
    "Strategy",
    "decide_ocr_recovery",
    "decide_registration_recovery",
    "diagnose",
    "enhance_for_registration",
    "evidence_grade_alignment_confidence",
    "plan_recovery",
    "validate_cms1500_registration_content",
]
