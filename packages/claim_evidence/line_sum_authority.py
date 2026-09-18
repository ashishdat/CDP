"""When box-28 OCR is empty, invalid, or strongly contradicts observed lines,
prefer LINE_TOTALS_RECONCILED from service-line ink (never invent amounts).

AUTO on line-sum alone is fail-closed: require dual-engine line agreement or
currency-shaped box-28 / DI corroboration within tolerance (hard-15 gate).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


_CHARGE_FIELDS = ("total_charge", "total_charges", "charges", "charge_amount")
_INDEPENDENT_ENGINES = frozenset({"paddleocr", "rapidocr", "azure_document_intelligence_read"})


def parse_currency(value: object) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return Decimal(re.sub(r"[^0-9.-]", "", raw))
    except (InvalidOperation, ValueError):
        return None


def format_currency(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


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
    text = format_currency(amount)
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
    return format_currency(sum(charges, Decimal(0)))


def _currency_digit_string(amount: object) -> str:
    text = str(amount or "").strip().lstrip("$").replace(",", "")
    if not text:
        return ""
    if "." in text:
        text = text.split(".", 1)[0]
    return re.sub(r"\D", "", text)


def is_currency_digit_drop_twin(left: object, right: object) -> bool:
    """True when one reading is a truncated digit-prefix of the other (1–2 digits)."""
    a, b = _currency_digit_string(left), _currency_digit_string(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if not longer.startswith(shorter):
        return False
    if not (1 <= (len(longer) - len(shorter)) <= 2):
        return False
    extra = longer[len(shorter) :]
    if extra and set(extra) <= {"0"}:
        return False
    return True


def amounts_within_tolerance(
    left: object,
    right: object,
    *,
    absolute: Decimal = Decimal("1.00"),
    relative: Decimal = Decimal("0.05"),
) -> bool:
    a, b = parse_currency(left), parse_currency(right)
    if a is None or b is None:
        return False
    diff = abs(a - b)
    target = max(abs(a), abs(b), Decimal(1))
    return diff <= max(absolute, target * relative)


def amounts_corroborate(left: object, right: object) -> bool:
    """Box-28 / DI may AUTO-confirm line-sum when equal, twin, or within tolerance."""
    if parse_currency(left) is None or parse_currency(right) is None:
        return False
    if amounts_within_tolerance(left, right):
        return True
    return is_currency_digit_drop_twin(left, right)


def _engine_family(engine: object) -> str:
    name = str(engine or "").strip().casefold()
    # gpt-4o is a residual reader, not an independent OCR engine for LINE_TOTALS
    # dual-engine AUTO (paddle+gpt4o agreeing on the same wrong amount → FA).
    if "gpt4o" in name or "gpt-4o" in name:
        return "azure_gpt4o_crop"
    if "azure" in name or "document_intelligence" in name:
        return "azure_document_intelligence_read"
    if "rapid" in name:
        return "rapidocr"
    if "paddle" in name:
        return "paddleocr"
    if "tesseract" in name:
        return "tesseract"
    return name


def _shaped_candidate_amounts(candidates: list[dict] | None) -> dict[str, Decimal]:
    """Map independent engine family → first currency-shaped amount."""
    by_engine: dict[str, Decimal] = {}
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        family = _engine_family(cand.get("engine") or cand.get("producing_engine"))
        if family not in _INDEPENDENT_ENGINES or family in by_engine:
            continue
        parsed = parse_currency(cand.get("value") or cand.get("raw_value"))
        if parsed is None:
            continue
        by_engine[family] = parsed
    return by_engine


def line_has_dual_engine_agreement(line: dict) -> bool:
    """True when ≥2 independent engines agree on the same currency amount.

    Exact / $1 tolerance only — digit-drop twins are NOT dual-engine agreement
    for LINE_TOTALS AUTO (13↔131 class false accepts on hard-15).
    """
    amounts = _shaped_candidate_amounts(line.get("candidates") if isinstance(line, dict) else None)
    if len(amounts) < 2:
        return False
    values = list(amounts.values())
    primary = values[0]
    return all(
        amounts_within_tolerance(
            format_currency(primary),
            format_currency(other),
            absolute=Decimal("1.00"),
            relative=Decimal("0"),
        )
        for other in values[1:]
    )


def dual_engine_line_fraction(service_lines: list[dict] | None) -> tuple[int, int]:
    """Return (agreed_lines, observed_charge_lines)."""
    agreed = 0
    observed = 0
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        has_charge = any(parse_currency(line.get(k)) is not None for k in _CHARGE_FIELDS)
        if not has_charge:
            continue
        observed += 1
        if line_has_dual_engine_agreement(line):
            agreed += 1
    return agreed, observed


def line_sum_auto_eligible(
    service_lines: list[dict] | None,
    *,
    box28_value: object = None,
    corroborating_values: list[object] | None = None,
) -> tuple[bool, str]:
    """Gate LINE_TOTALS E6 AUTO (fail-closed).

    Eligible when:
      - currency-shaped box-28 / DI corroborates the line sum, or
      - multi-line (≥2) and every line charge has exact dual-engine agreement.

    Single-line dual-engine agreement alone is NOT enough — hard-15 showed
    paddle+rapid both reading the same wrong amount (222 vs 233, 200 vs 22).
    """
    total = line_sum_total(service_lines)
    if total is None:
        return False, "NO_LINE_CHARGES"

    corroborators = []
    for value in [box28_value, *(corroborating_values or [])]:
        parsed = parse_currency(value)
        if parsed is None or is_suspicious_tiny_total(parsed):
            continue
        corroborators.append(value)
    if corroborators:
        if any(amounts_corroborate(total, value) for value in corroborators):
            return True, "BOX28_OR_DI_CORROBORATED"
        # Currency-shaped box-28 / DI disagrees with line-sum → HITL, not false STP.
        return False, "BOX28_OR_DI_CONFLICT"

    agreed, observed = dual_engine_line_fraction(service_lines)
    if observed == 0:
        return False, "NO_LINE_CHARGES"
    if observed == 1:
        return False, "SINGLE_LINE_REQUIRES_DI"
    if agreed >= observed and observed >= 2:
        return True, "DUAL_ENGINE_LINE_AGREEMENT"
    return False, "MULTI_LINE_UNCORROBORATED"
