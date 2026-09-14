"""Cause-driven recovery planning primitives.

These primitives decide whether a failed extraction has enough evidence for a
single bounded recovery strategy. They do not execute extraction or alter V1
algorithms.
"""

from .diagnosis import Cause, Diagnosis, diagnose
from .ocr_recovery import OcrRecoveryDecision, decide_ocr_recovery
from .planner import RecoveryPlan, Strategy, plan_recovery

__all__ = [
    "Cause",
    "Diagnosis",
    "OcrRecoveryDecision",
    "RecoveryPlan",
    "Strategy",
    "decide_ocr_recovery",
    "diagnose",
    "plan_recovery",
]
