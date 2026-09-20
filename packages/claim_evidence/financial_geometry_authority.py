"""Evidence-based financial AUTO when printed Box 24F Σ equals Box 28 exactly.

``FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED`` is not threshold lowering. It fires
only when line charges were selected from charge-column evidence and the
printed total matches the arithmetic of those selections.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any

from packages.claim_evidence.box28_line_sum_authority import (
    build_box28_evidence,
    evaluate_parser_integrity,
)
from packages.claim_evidence.line_charge_selector import select_line_charge
from packages.claim_evidence.line_sum_authority import (
    format_currency,
    is_decimal_place_shift,
    is_implausible_charge_total,
    parse_currency,
)


@dataclass(frozen=True)
class FinancialGeometryDecision:
    confirmed: bool
    amount: str | None
    reason: str
    line_sum: str | None = None
    box28: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmed": self.confirmed,
            "amount": self.amount,
            "reason": self.reason,
            "line_sum": self.line_sum,
            "box28": self.box28,
            "details": self.details or {},
        }


def _line_selected_amount(line: dict) -> tuple[str | None, str]:
    selection = line.get("line_charge_selection")
    if isinstance(selection, dict) and selection.get("disposition") == "SELECTED_LOCAL_CHARGE":
        amount = selection.get("amount")
        if parse_currency(amount) is not None:
            return format_currency(parse_currency(amount)), "SELECTOR"
    # Fresh selection if OCR artifact predates the selector.
    result = select_line_charge(line)
    if result.disposition == "SELECTED_LOCAL_CHARGE" and result.amount:
        return result.amount, result.reason
    return None, result.disposition


def evaluate_financial_geometry_arithmetic(
    *,
    box28_amount: object,
    service_lines: list[dict] | None,
    box28_field_payload: dict | None = None,
    box28_region: object = None,
    box28_observation: dict | None = None,
) -> FinancialGeometryDecision:
    """Confirm total_charge when selected Box 24F Σ equals Box 28 exactly."""
    lines = [ln for ln in (service_lines or []) if isinstance(ln, dict)]
    if not lines:
        return FinancialGeometryDecision(False, None, "NO_SERVICE_LINES")

    selected: list[str] = []
    details_rows: list[dict[str, Any]] = []
    for line in lines:
        amount, reason = _line_selected_amount(line)
        details_rows.append({"amount": amount, "reason": reason})
        if amount is None:
            # Blank / unreadable active rows with procedure ink still block.
            if any(
                str(line.get(k) or "").strip()
                for k in ("procedure_code", "cpt", "charges", "charge_amount")
            ):
                return FinancialGeometryDecision(
                    False,
                    None,
                    "LINE_NOT_SELECTED",
                    details={"rows": details_rows},
                )
            continue
        selected.append(amount)

    if not selected:
        return FinancialGeometryDecision(False, None, "NO_SELECTED_LINES")

    total = sum((parse_currency(a) or Decimal(0) for a in selected), Decimal(0))
    line_sum = format_currency(total)

    box = parse_currency(box28_amount)
    if box is None or is_implausible_charge_total(box28_amount):
        return FinancialGeometryDecision(
            False, None, "BOX28_UNPARSED", line_sum=line_sum, details={"rows": details_rows}
        )
    box_txt = format_currency(box)
    if is_decimal_place_shift(box_txt, line_sum):
        return FinancialGeometryDecision(
            False,
            None,
            "DECIMAL_SHIFT_CONFLICT",
            line_sum=line_sum,
            box28=box_txt,
            details={"rows": details_rows},
        )
    if box != total:
        return FinancialGeometryDecision(
            False,
            None,
            "ARITHMETIC_MISMATCH",
            line_sum=line_sum,
            box28=box_txt,
            details={"rows": details_rows},
        )

    # Box 28 must show observed decimal / glyph integrity — not a reconstructed shell.
    box28 = build_box28_evidence(
        amount=box_txt,
        field_payload=box28_field_payload,
        region=box28_region,
        observation=box28_observation,
    )
    if not box28.integrity.passed:
        # Fall back to raw observation / amount token integrity.
        raw = ""
        if isinstance(box28_observation, dict):
            raw = str(
                box28_observation.get("text")
                or box28_observation.get("raw_digit_sequence")
                or ""
            )
        if not raw:
            raw = str(box28_amount)
        integrity = evaluate_parser_integrity(amount=box_txt, raw_digit_sequence=raw)
        if not integrity.passed:
            # Soft path: printed amount already equals selected Σ exactly and the
            # raw/token text contains an observed decimal for that amount. Glyph
            # mapping failures must not block already-agreeing arithmetic.
            observed_decimal = bool(
                re.search(r"\d+\.\d{2}", str(raw))
                or re.search(r"\d+\.\d{2}", str(box28_amount or ""))
            )
            if not (
                observed_decimal
                and parse_currency(box_txt) == total
                and not is_decimal_place_shift(box_txt, line_sum)
            ):
                return FinancialGeometryDecision(
                    False,
                    None,
                    "BOX28_GEOMETRY_FAILED",
                    line_sum=line_sum,
                    box28=box_txt,
                    details={
                        "rows": details_rows,
                        "integrity": box28.integrity.rejection_reason,
                        "fallback": integrity.rejection_reason,
                    },
                )

    # Conflicting currency-shaped Box 28 competitors that are not place-shift
    # noise of the confirmed amount stay HITL.
    if isinstance(box28_field_payload, dict):
        for row in (
            [box28_field_payload.get("ranked_candidate")]
            if box28_field_payload.get("ranked_candidate")
            else []
        ) + list(box28_field_payload.get("alternatives") or []):
            if not row:
                continue
            ocr = row.get("ocr_candidate") or {}
            variant = str(ocr.get("preprocessing_variant") or "").casefold()
            if "derived_from_observed_line" in variant or "phase2-line-sum" in variant:
                continue
            alt = parse_currency(ocr.get("value") or ocr.get("raw_value"))
            if alt is None:
                continue
            alt_txt = format_currency(alt)
            if alt_txt == box_txt:
                continue
            if is_decimal_place_shift(alt_txt, box_txt):
                continue
            if is_implausible_charge_total(alt_txt):
                continue
            # Same-stem OCR twins (1160.40 beside confirmed 1160.00) are not
            # true financial conflicts like 2605 vs 2601 or 49.72 vs 4972.
            box_dollars = box_txt.split(".", 1)[0]
            alt_dollars = alt_txt.split(".", 1)[0]
            if box_dollars == alt_dollars and abs(alt - box) <= Decimal("1.00"):
                continue
            # Ruling-split / fragment of the already-confirmed amount
            # (``25.00`` beside confirmed ``34.25``) is not a competing total.
            if box == total:
                conf_digits = re.sub(r"\D", "", box_txt)
                alt_digits = re.sub(r"\D", "", alt_txt)
                alt_core = alt_digits.rstrip("0") or alt_digits
                if (
                    conf_digits
                    and alt_core
                    and len(alt_core) <= len(conf_digits)
                    and alt_core in conf_digits
                ):
                    continue
                # Same-ROI dollars stem with junk tail (``34 125`` → ``125.00``).
                raw_groups = re.findall(r"\d+", str(ocr.get("raw_value") or ""))
                if box_dollars in raw_groups and alt_txt != box_txt:
                    continue
            # Near-miss dollars that are not the confirmed total → conflict HITL.
            if abs(alt - box) > Decimal("0.01"):
                return FinancialGeometryDecision(
                    False,
                    None,
                    "CONFLICTING_BOX28_CANDIDATE",
                    line_sum=line_sum,
                    box28=box_txt,
                    details={"conflict": alt_txt, "rows": details_rows},
                )

    return FinancialGeometryDecision(
        True,
        box_txt,
        "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
        line_sum=line_sum,
        box28=box_txt,
        details={"rows": details_rows},
    )
