"""Cause-driven recovery planning primitives.

These primitives decide whether a failed extraction has enough evidence for a
single bounded recovery strategy. They do not execute extraction or alter V1
algorithms.
"""

from .diagnosis import Cause, Diagnosis, diagnose
from .planner import RecoveryPlan, plan_recovery

__all__ = ["Cause", "Diagnosis", "RecoveryPlan", "diagnose", "plan_recovery"]
