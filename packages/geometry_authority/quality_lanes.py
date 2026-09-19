"""CMS-1500 print-quality lanes for residual routing.

Lane A — clean machine print: local deterministic + Box 24F/28 reconciliation.
Lane B — overprinted / degraded: line removal + optional cloud crop.
Lane C — handwritten: handwriting / structured corroboration only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FormQualityLane(str, Enum):
    CLEAN_PRINTED = "CLEAN_PRINTED"
    OVERPRINTED_DEGRADED = "OVERPRINTED_DEGRADED"
    HANDWRITTEN = "HANDWRITTEN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class QualityLaneDecision:
    lane: FormQualityLane
    reasons: tuple[str, ...]
    allow_calibrated_direct: bool
    require_structured_corroboration: bool


def classify_cms1500_quality_lane(
    *,
    handwriting_signals: int = 0,
    overprint_signals: int = 0,
    clean_print_signals: int = 0,
) -> QualityLaneDecision:
    """Classify from observed evidence counts — not claim IDs."""
    if handwriting_signals >= 2 and handwriting_signals >= overprint_signals:
        return QualityLaneDecision(
            FormQualityLane.HANDWRITTEN,
            ("HANDWRITING_SIGNAL_DOMINANT",),
            allow_calibrated_direct=False,
            require_structured_corroboration=True,
        )
    if overprint_signals >= 2:
        return QualityLaneDecision(
            FormQualityLane.OVERPRINTED_DEGRADED,
            ("OVERPRINT_OR_DEGRADED_SIGNAL",),
            allow_calibrated_direct=False,
            require_structured_corroboration=False,
        )
    if clean_print_signals >= 1 or (
        handwriting_signals == 0 and overprint_signals == 0
    ):
        return QualityLaneDecision(
            FormQualityLane.CLEAN_PRINTED,
            ("CLEAN_PRINTED_DEFAULT",),
            allow_calibrated_direct=True,
            require_structured_corroboration=False,
        )
    return QualityLaneDecision(
        FormQualityLane.UNKNOWN,
        ("QUALITY_LANE_UNRESOLVED",),
        allow_calibrated_direct=False,
        require_structured_corroboration=True,
    )
