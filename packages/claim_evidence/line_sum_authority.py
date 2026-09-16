"""When box-28 OCR is empty, invalid, or strongly contradicts observed lines,
prefer LINE_TOTALS_RECONCILED from service-line ink (never invent amounts)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


_CHARGE_FIELDS = ("total_charge", "total_charges", "charges", "charge_amount")


def parse_currency(value: object) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return Decimal(re.sub(r"[^0-9.-]", "", raw))
    except (InvalidOperation, ValueError):
        return None


def observed_line_charges(service_lines: list[dict] | None) -> list[Decimal]:
    charges: list[Decimal] = []
    for line in service_lines or []:
        for key in _CHARGE_FIELDS:
            parsed = parse_currency(line.get(key))
            if parsed is not None and parsed >= 0:
                charges.append(parsed)
                break
    return charges


def is_suspicious_tiny_total(amount: Decimal) -> bool:
    """Match field-cascade CURRENCY_SUSPICIOUS_TINY (single digit before cents)."""
    text = format(amount.quantize(Decimal("0.01")), "f")
    return bool(re.fullmatch(r"[0-9]\.\d{2}", text))


def should_defer_box28_to_line_sum(
    box28_value: object,
    service_lines: list[dict] | None,
    *,
    relative_contradiction: Decimal = Decimal("0.50"),
    min_lines: int = 2,
) -> bool:
    """Return True when box-28 should be cleared so LINE_TOTALS_RECONCILED owns E6."""
    charges = observed_line_charges(service_lines)
    if not charges:
        return False
    box = parse_currency(box28_value)
    if box is None:
        return True
    if is_suspicious_tiny_total(box):
        return True
    observed = sum(charges, Decimal(0))
    if observed <= 0:
        return False
    difference = abs(box - observed)
    tolerance = max(Decimal("1.00"), observed * relative_contradiction)
    # Multi-line: defer on strong contradiction (existing rule).
    if len(charges) >= min_lines:
        return difference > tolerance
    # Single observed line: defer only when box-28 is wildly off the line
    # amount (Track-B residual: box-28 ``22.00`` vs line ``305.00``). Plausible
    # near-miss box-28 (e.g. 400 vs 305) stays with OCR — do not invent.
    return difference > tolerance


def line_sum_total(service_lines: list[dict] | None) -> str | None:
    charges = observed_line_charges(service_lines)
    if not charges:
        return None
    return format(sum(charges, Decimal(0)).quantize(Decimal("0.01")), "f")
