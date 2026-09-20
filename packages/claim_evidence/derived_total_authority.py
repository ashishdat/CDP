"""Derive total_charge from complete verified Box 24F lines when Box 28 is blank.

``DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES`` is an operational arithmetic
value, not a printed Box 28 OCR prediction. It must never fire over
unreadable / present Box 28 ink.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from packages.claim_evidence.box28_blankness import (
    Box28Blankness,
    classify_box28_blankness,
)
from packages.claim_evidence.line_charge_selector import select_line_charge
from packages.claim_evidence.line_sum_authority import (
    format_currency,
    parse_currency,
)
from packages.geometry_authority.cms1500_regions import (
    charge_region_verdict,
    is_pos_like_currency,
)


@dataclass(frozen=True)
class DerivedTotalDecision:
    derived: bool
    amount: str | None
    reason: str
    line_values: tuple[str, ...] = ()
    blankness: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived": self.derived,
            "amount": self.amount,
            "reason": self.reason,
            "line_values": list(self.line_values),
            "blankness": self.blankness,
            "details": self.details or {},
            "value_origin": (
                "DERIVED_FROM_VERIFIED_SERVICE_LINES" if self.derived else None
            ),
            "printed_box28_value": None if self.derived else None,
            "box28_status": self.blankness,
        }


def _bbox(raw: object) -> tuple[float, float, float, float] | None:
    if isinstance(raw, dict) and raw.get("x0") is not None:
        try:
            return (
                float(raw["x0"]),
                float(raw["y0"]),
                float(raw["x1"]),
                float(raw["y1"]),
            )
        except (TypeError, ValueError, KeyError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
        except (TypeError, ValueError):
            return None
    return None


def _line_has_independent_charge_evidence(line: dict) -> bool:
    selection = line.get("line_charge_selection")
    if isinstance(selection, dict):
        if selection.get("disposition") == "SELECTED_LOCAL_CHARGE":
            engines = selection.get("supporting_engines") or []
            return len(engines) >= 1 and parse_currency(selection.get("amount")) is not None
        return False
    result = select_line_charge(line)
    return result.disposition == "SELECTED_LOCAL_CHARGE" and result.amount is not None


def _line_charge_geometry_valid(line: dict) -> bool:
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        bbox = _bbox(cand.get("bounding_box"))
        if bbox is None:
            continue
        verdict = charge_region_verdict(bbox, already_reference=True)
        if verdict.authorised:
            return True
    region = _bbox(line.get("canonical_region") or line.get("ocr_region"))
    if region is None:
        return False
    return charge_region_verdict(region, already_reference=True).authorised


def _line_not_pos_or_units_bleed(line: dict, amount: str) -> bool:
    if is_pos_like_currency(amount) and amount in {
        "11.00",
        "12.00",
        "21.00",
        "22.00",
        "23.00",
    }:
        return False
    selection = line.get("line_charge_selection")
    if isinstance(selection, dict):
        rejected = selection.get("rejected") or []
        for row in rejected:
            if not isinstance(row, dict):
                continue
            if row.get("value") == amount and row.get("reason") in {
                "POS_REGION_OVERLAP",
                "OUTSIDE_CHARGE_COLUMN",
                "UNITS_CONCAT_BLEED",
                "BARE_DIGIT_SOUP",
            }:
                return False
    return True


def _has_adjustment_or_credit(line: dict) -> bool:
    for key in ("charges", "charge_amount", "raw_charges"):
        text = str(line.get(key) or "")
        if "CR" in text.upper() or text.strip().startswith("("):
            return True
    return False


def _selected_amount(line: dict) -> str | None:
    selection = line.get("line_charge_selection")
    if isinstance(selection, dict) and selection.get("disposition") == "SELECTED_LOCAL_CHARGE":
        amount = selection.get("amount")
        if parse_currency(amount) is not None:
            return format_currency(parse_currency(amount))
    result = select_line_charge(line)
    if result.disposition == "SELECTED_LOCAL_CHARGE" and result.amount:
        return result.amount
    return None


def can_derive_total_from_lines(
    *,
    document_family: str,
    registration_verified: bool,
    box28_blankness: str,
    service_lines: list[dict] | None,
) -> tuple[bool, str]:
    """Gate for DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES."""
    family = str(document_family or "").upper().replace("-", "")
    if family not in {"CMS1500", "CMS_1500"}:
        return False, "NOT_CMS1500"
    if not registration_verified:
        return False, "REGISTRATION_UNVERIFIED"
    if box28_blankness != Box28Blankness.CONFIRMED_BLANK.value:
        return False, f"BOX28_NOT_CONFIRMED_BLANK:{box28_blankness}"

    lines = [ln for ln in (service_lines or []) if isinstance(ln, dict)]
    if not lines:
        return False, "NO_SERVICE_LINES"

    populated: list[dict] = []
    for line in lines:
        has_procedure = any(
            str(line.get(k) or "").strip()
            for k in ("procedure_code", "cpt", "hcpcs_code")
        )
        has_charge_signal = any(
            line.get(k) not in (None, "")
            for k in ("charges", "charge_amount", "candidates")
        )
        if has_procedure or has_charge_signal:
            populated.append(line)

    if not populated:
        return False, "NO_POPULATED_SERVICE_ROWS"

    amounts: list[str] = []
    for line in populated:
        selection = line.get("line_charge_selection")
        if isinstance(selection, dict):
            disp = selection.get("disposition")
            if disp in {"AMBIGUOUS_LINE_CHARGE", "UNREADABLE_LINE_CHARGE"}:
                return False, f"LINE_{disp}"
        if not _line_has_independent_charge_evidence(line):
            return False, "LINE_MISSING_INDEPENDENT_CHARGE_EVIDENCE"
        if not _line_charge_geometry_valid(line):
            return False, "LINE_CHARGE_GEOMETRY_INVALID"
        amount = _selected_amount(line)
        if amount is None:
            return False, "LINE_AMOUNT_UNSELECTED"
        if not _line_not_pos_or_units_bleed(line, amount):
            return False, "LINE_POS_OR_UNITS_BLEED"
        if _has_adjustment_or_credit(line):
            return False, "ADJUSTMENT_OR_CREDIT_LINE"
        amounts.append(amount)

    total = sum((parse_currency(a) or Decimal(0) for a in amounts), Decimal(0))
    if total <= 0:
        return False, "LINE_SUM_NON_POSITIVE"
    return True, "OK"


def evaluate_derived_total_from_complete_verified_lines(
    *,
    document_family: str,
    registration_verified: bool,
    service_lines: list[dict] | None,
    box28_amount: object = None,
    box28_field_payload: dict | None = None,
    box28_observation: dict | None = None,
    box28_region: object = None,
    box28_roi_image: object = None,
    blankness_status: str | None = None,
) -> DerivedTotalDecision:
    """Emit derived total only when Box 28 is confirmed blank and lines are clean."""
    if blankness_status is None:
        blank = classify_box28_blankness(
            box28_amount=box28_amount,
            field_payload=box28_field_payload,
            observation=box28_observation,
            roi_image=box28_roi_image,
            region=box28_region,
        )
        blankness = blank.status.value
        blank_details = blank.to_dict()
    else:
        blankness = str(blankness_status)
        blank_details = {"status": blankness, "reason": "CALLER_PROVIDED"}

    # Never derive over printed / unreadable ink.
    if blankness == Box28Blankness.INK_PRESENT_UNREADABLE.value:
        return DerivedTotalDecision(
            False,
            None,
            "BOX28_INK_PRESENT_UNREADABLE",
            blankness=blankness,
            details=blank_details,
        )
    if blankness == Box28Blankness.ROI_UNUSABLE.value:
        return DerivedTotalDecision(
            False,
            None,
            "BOX28_ROI_UNUSABLE",
            blankness=blankness,
            details=blank_details,
        )
    if blankness == Box28Blankness.INK_OBSERVED.value:
        return DerivedTotalDecision(
            False,
            None,
            "BOX28_INK_OBSERVED",
            blankness=blankness,
            details=blank_details,
        )

    ok, reason = can_derive_total_from_lines(
        document_family=document_family,
        registration_verified=registration_verified,
        box28_blankness=blankness,
        service_lines=service_lines,
    )
    if not ok:
        return DerivedTotalDecision(
            False,
            None,
            reason,
            blankness=blankness,
            details=blank_details,
        )

    lines = [ln for ln in (service_lines or []) if isinstance(ln, dict)]
    amounts: list[str] = []
    for line in lines:
        has_procedure = any(
            str(line.get(k) or "").strip()
            for k in ("procedure_code", "cpt", "hcpcs_code")
        )
        has_charge_signal = any(
            line.get(k) not in (None, "")
            for k in ("charges", "charge_amount", "candidates")
        )
        if not (has_procedure or has_charge_signal):
            continue
        amount = _selected_amount(line)
        if amount is None:
            return DerivedTotalDecision(
                False, None, "LINE_AMOUNT_UNSELECTED", blankness=blankness, details=blank_details
            )
        amounts.append(amount)

    total = format_currency(
        sum((parse_currency(a) or Decimal(0) for a in amounts), Decimal(0))
    )
    return DerivedTotalDecision(
        True,
        total,
        "DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES",
        line_values=tuple(amounts),
        blankness=blankness,
        details={
            **blank_details,
            "line_count": len(amounts),
            "line_values": list(amounts),
            "derivation": "SUM(Box24F)",
            "source": "CMS1500_BOX24F_ARITHMETIC",
            "box28_status": blankness,
            "value_origin": "DERIVED_FROM_VERIFIED_SERVICE_LINES",
            "printed_box28_value": None,
        },
    )
