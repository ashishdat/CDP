"""Field normalization, dispatched by `FieldRegion.field_type`.

Each processor takes raw OCR text and returns `(normalized_value, ok)`;
`ok=False` doesn't mean "reject the field" -- it means "normalization
couldn't make sense of this raw text", which the validation worker (Phase
3) treats as an ordinary validation failure, not a crash. Processors are
deliberately permissive parsers, not validators -- e.g. `normalize_npi`
accepts any 10-digit string; the Luhn checksum lives in
`packages.validation_rules` (Phase 3), not here, because "is this
syntactically a date/NPI/amount" and "is this NPI actually valid" are
different concerns evaluated by different pipeline stages.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = ["%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%m/%d/%y", "%Y%m%d", "%m%d%Y", "%m%d%y"]


def normalize_text(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", " ", raw.strip())
    return cleaned, bool(cleaned)


def normalize_date(raw: str) -> tuple[str | None, bool]:
    cleaned = re.sub(r"\s+", "/", raw.strip())
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()  # noqa: DTZ007 -- paper-form dates have no timezone
        except ValueError:
            continue
        # 2-digit years: pivot at 50 (>=50 -> 19xx, <50 -> 20xx), a common
        # convention for claims data spanning both centuries.
        if parsed.year < 100:
            parsed = parsed.replace(year=parsed.year + (1900 if parsed.year >= 50 else 2000))
        return parsed.isoformat(), True
    return None, False


def normalize_currency(raw: str) -> tuple[Decimal | None, bool]:
    # Table-border OCR commonly leaves a leading/trailing vertical bar. It is
    # not part of a claim amount and is removed before sign interpretation.
    source = raw.strip().strip("|").strip()
    parenthesized = source.startswith("(") and source.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", source)
    if not cleaned:
        return None, False
    if parenthesized and not cleaned.startswith("-"):
        cleaned = f"-{cleaned}"
    try:
        return Decimal(cleaned).quantize(Decimal("0.01")), True
    except InvalidOperation:
        return None, False


def normalize_npi(raw: str) -> tuple[str | None, bool]:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return digits, True
    return None, False


def normalize_tax_id(raw: str) -> tuple[str | None, bool]:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        return digits, True
    return None, False


def normalize_code(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", "", raw.strip().upper())
    return cleaned, bool(cleaned)


def normalize_checkbox(raw: str) -> tuple[bool | None, bool]:
    cleaned = raw.strip().upper()
    if cleaned in ("X", "[X]", "YES"):
        return True, True
    if cleaned in ("", "[ ]", "NO"):
        return False, True
    return None, False


_PROCESSORS = {
    "text": normalize_text,
    "date": normalize_date,
    "currency": normalize_currency,
    "npi": normalize_npi,
    "tax_id": normalize_tax_id,
    "code": normalize_code,
    "checkbox": normalize_checkbox,
}


def normalize(field_type: str, raw: str) -> tuple[str | None, bool]:
    processor = _PROCESSORS.get(field_type, normalize_text)
    value, ok = processor(raw)
    return (str(value) if value is not None else None), ok
