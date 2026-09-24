"""Honest residual taxonomy for Independent-class HITL (no auto-accept)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping, Sequence


class ResidualClass(StrEnum):
    RECOVERABLE = "RECOVERABLE"
    INK_ABSENT = "INK_ABSENT"
    POLICY_HOLD = "POLICY_HOLD"
    REL_CONFLICT = "REL_CONFLICT"
    UNKNOWN = "UNKNOWN"


_SCALE_RIVAL = "CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL"
_POLICY_REASONS = frozenset(
    {
        "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD",
        "C3_INDEPENDENT_EVIDENCE_REQUIRED",
        "LINE_TOTALS_UNCORROBORATED",
        "CONFLICT_MARGIN_TOO_SMALL",
        "MISSING_E4_DETERMINISTIC_VALIDATION",
        "MISSING_E2_INDEPENDENT_CONFIRMATION",
        _SCALE_RIVAL,
    }
)


def classify_hitl_residual(
    *,
    hitl_track: str | None,
    critical_blockers: Sequence[str] | None,
    reason_codes: Sequence[str] | None = None,
    field_reasons: Mapping[str, Sequence[str]] | None = None,
    relationship: str | None = None,
) -> ResidualClass:
    """Classify why a HITL claim remains unresolved (precision-safe)."""
    miss = sorted(critical_blockers or [])
    reasons = {str(r) for r in (reason_codes or [])}
    for codes in (field_reasons or {}).values():
        reasons.update(str(c) for c in codes)

    # Empty critical blockers → usually insured_name spouse conflict.
    if not miss:
        rel = (relationship or "").strip().casefold()
        if rel and rel not in {"self", "1", "01"}:
            return ResidualClass.REL_CONFLICT
        if "FIELD_CONFLICT:insured_name" in reasons or any(
            "insured_name" in r for r in reasons
        ):
            return ResidualClass.REL_CONFLICT
        return ResidualClass.POLICY_HOLD

    if _SCALE_RIVAL in reasons or reasons & _POLICY_REASONS:
        # Observed value held by evidence policy — not missing ink.
        if miss == ["total_charge"] or "total_charge" in miss:
            return ResidualClass.POLICY_HOLD

    if "NO_NONEMPTY_CANDIDATE" in reasons or miss == ["patient_dob"]:
        # Empty / fragment DOB — ink absent unless a residual later finds calendar.
        return ResidualClass.INK_ABSENT

    if hitl_track == "UNSTRUCTURED_DI" and "patient_name" in miss and len(miss) == 1:
        return ResidualClass.INK_ABSENT

    if hitl_track == "UNSTRUCTURED_DI" and set(miss) <= {
        "insured_id_number",
        "patient_dob",
        "patient_name",
        "total_charge",
    }:
        # Unstructured residuals without dual-corroboration evidence stay HITL.
        # Form-label names / missing charge are ink-absent, not inventable.
        if "total_charge" in miss and len(miss) == 1:
            return ResidualClass.INK_ABSENT
        if "patient_dob" in miss or "insured_id_number" in miss:
            return ResidualClass.INK_ABSENT

    if hitl_track == "FIELD_INK" and miss == ["total_charge"]:
        # Charge observed but uncorroborated — policy hold until DI/line agree.
        return ResidualClass.POLICY_HOLD

    # Multi-field weak: treat as recoverable only when no policy hold codes.
    if reasons & _POLICY_REASONS:
        return ResidualClass.POLICY_HOLD
    if miss:
        return ResidualClass.RECOVERABLE
    return ResidualClass.UNKNOWN


def classify_row(row: Mapping[str, Any]) -> ResidualClass:
    if row.get("disposition") != "HITL":
        return ResidualClass.UNKNOWN
    field_reasons: dict[str, list[str]] = {}
    fields = row.get("fields")
    if isinstance(fields, Mapping):
        for name, body in fields.items():
            if isinstance(body, Mapping) and body.get("reasons"):
                field_reasons[str(name)] = [str(c) for c in body.get("reasons") or []]
    reason_codes = list(row.get("reason_codes") or [])
    # Form-label / placeholder junk is not recoverable ink.
    for codes in field_reasons.values():
        joined = " ".join(codes).upper()
        if "INVALID_FORMAT" in joined or "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" in joined:
            reason_codes.append("CALIBRATED_CONFIDENCE_BELOW_THRESHOLD")
    return classify_hitl_residual(
        hitl_track=row.get("hitl_track"),
        critical_blockers=row.get("critical_blockers"),
        reason_codes=reason_codes,
        field_reasons=field_reasons,
        relationship=row.get("relationship") or row.get("rel_code"),
    )
