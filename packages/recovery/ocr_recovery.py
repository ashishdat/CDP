"""Bounded OCR recovery helpers for regional field extraction.

Uses the cause-driven recovery planner to authorize at most one alternate
preprocessing profile when primary regional OCR returns empty text.
"""

from __future__ import annotations

from dataclasses import dataclass

from .diagnosis import Cause, diagnose
from .planner import Strategy, plan_recovery

# Mild fallbacks only — never re-apply NAME_STROKE_V2 (Phase 8.10B regression).
# REGIONAL_DEFAULT is intentionally omitted: empty free-text/name crops must not
# be re-read with digit-preserving prep (false-accept risk on CPT/IDs).
_ALTERNATE_PROFILES: dict[str, str] = {
    "DIGIT_PRESERVING_V2": "GENERAL_TEXT",
    "DATE_DELIMITER_V2": "GENERAL_TEXT",
    "CURRENCY_DECIMAL_V2": "DIGIT_PRESERVING_V2",
    "ALPHANUMERIC_STROKE_V2": "GENERAL_TEXT",
    "NAME_STROKE_V2": "GENERAL_TEXT",
    "GENERAL_TEXT": "DIGIT_PRESERVING_V2",
    "NUMERIC": "DIGIT_PRESERVING_V2",
    "DATE": "DATE_DELIMITER_V2",
    "NAME": "GENERAL_TEXT",
}


@dataclass(frozen=True)
class OcrRecoveryDecision:
    attempt_alternate: bool
    alternate_profile: str | None
    cause: Cause
    strategy: Strategy
    reason: str


def decide_ocr_recovery(
    *,
    primary_profile: str,
    primary_text: str,
    strategy_available: bool = True,
) -> OcrRecoveryDecision:
    """Authorize one alternate OCR prep when the primary regional read is empty."""
    if str(primary_text or "").strip():
        return OcrRecoveryDecision(
            False, None, Cause.UNDETERMINED, Strategy.NONE, "Primary OCR returned text"
        )
    diagnosis = diagnose(
        ["regional_ocr_empty"],
        ocr_attempted=True,
        evidence=(f"primary_profile={primary_profile}",),
    )
    plan = plan_recovery(diagnosis, strategy_available=strategy_available)
    if not plan.executable or plan.strategy is not Strategy.ALTERNATIVE_OCR:
        return OcrRecoveryDecision(
            False, None, diagnosis.primary_cause, plan.strategy, plan.reason
        )
    alternate = _ALTERNATE_PROFILES.get(primary_profile)
    if not alternate or alternate == primary_profile:
        return OcrRecoveryDecision(
            False,
            None,
            diagnosis.primary_cause,
            Strategy.NONE,
            "No distinct alternate profile for primary",
        )
    return OcrRecoveryDecision(
        True,
        alternate,
        diagnosis.primary_cause,
        plan.strategy,
        f"One alternate profile attempt: {alternate}",
    )
