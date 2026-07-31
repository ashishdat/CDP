"""Numeric/currency range validation (parsing already happened in
`workers.standard_form_extraction.field_processors`; this checks the
parsed value makes business sense)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class NumericCheckResult:
    ok: bool
    reason: str | None = None


def check_non_negative_currency(amount: Decimal) -> NumericCheckResult:
    if amount < 0:
        return NumericCheckResult(ok=False, reason=f"{amount} is negative")
    return NumericCheckResult(ok=True)


def check_positive_units(units: Decimal) -> NumericCheckResult:
    if units <= 0:
        return NumericCheckResult(ok=False, reason=f"{units} must be greater than zero")
    return NumericCheckResult(ok=True)
