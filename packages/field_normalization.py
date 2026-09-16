"""Pure field normalization shared by runtime workers and domain policies."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = [
    "%Y-%m-%d",  # already-normalized ISO from extractors
    "%m-%d-%Y",
    "%m/%d/%Y",
    "%m-%d-%y",
    "%m/%d/%y",
    "%Y%m%d",
    "%m%d%Y",
    "%m%d%y",
]


def normalize_text(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", " ", raw.strip())
    return cleaned, bool(cleaned)


def normalize_date(raw: str) -> tuple[str | None, bool]:
    # Collapse per-glyph OCR spaces between digits before delimiter normalization.
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", raw.strip())
    # OCR often inserts dots inside digit groups ("0.4/03/20.02" -> "04/03/2002").
    cleaned = re.sub(r"(?<=\d)\.(?=\d)", "", cleaned)
    # Preserve ISO dashes; only rewrite whitespace/slash delimiters for US forms.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        try:
            return datetime.strptime(cleaned, "%Y-%m-%d").date().isoformat(), True  # noqa: DTZ007
        except ValueError:
            return None, False
    cleaned = re.sub(r"[.\s]*/[.\s]*", "/", cleaned)
    cleaned = re.sub(r"\s+", "/", cleaned)
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
        return parsed.isoformat(), True
    return None, False


def normalize_currency(raw: str) -> tuple[Decimal | None, bool]:
    source = raw.strip().strip("|").strip()
    parenthesized = source.startswith("(") and source.endswith(")")
    # OCR commonly confuses 0 with O inside amounts.
    source = source.upper().replace("O", "0")
    cleaned = re.sub(r"[^0-9.\-]", "", source)
    if not cleaned:
        return None, False
    if parenthesized and not cleaned.startswith("-"):
        cleaned = f"-{cleaned}"
    # Upscaled currency crops often drop the decimal point ("85650" for 856.50).
    if "." not in cleaned and re.fullmatch(r"-?\d{3,}", cleaned):
        cleaned = f"{cleaned[:-2]}.{cleaned[-2:]}"
    try:
        return Decimal(cleaned).quantize(Decimal("0.01")), True
    except InvalidOperation:
        return None, False


def normalize_npi(raw: str) -> tuple[str | None, bool]:
    digits = re.sub(r"\D", "", raw)
    return (digits, True) if len(digits) == 10 else (None, False)


def normalize_tax_id(raw: str) -> tuple[str | None, bool]:
    digits = re.sub(r"\D", "", raw)
    return (digits, True) if len(digits) == 9 else (None, False)


def normalize_code(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", "", raw.strip().upper())
    return cleaned, bool(cleaned)


def normalize_member_id(raw: str) -> tuple[str | None, bool]:
    """Compact member/subscriber IDs by stripping OCR spacing and punctuation."""
    compact = re.sub(r"[^A-Za-z0-9]", "", raw.strip().upper())
    if re.fullmatch(r"[A-Z0-9]{5,24}", compact):
        return compact, True
    return (compact or None), bool(compact)


def normalize_icd(raw: str) -> tuple[str | None, bool]:
    """Normalize ICD-10-CM style codes and repair common OCR letter/digit swaps."""
    cleaned = re.sub(r"\s+", "", raw.strip().upper())
    if not cleaned:
        return None, False
    # Leading I/O are frequently read as 1/0 on diagnosis crops (I10 -> 110).
    if re.fullmatch(r"[10]\d{1,2}(?:\.[0-9A-Z]{1,4})?", cleaned):
        cleaned = ("I" if cleaned[0] == "1" else "O") + cleaned[1:]
    if re.fullmatch(r"[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?", cleaned):
        return cleaned, True
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
    "member_id": normalize_member_id,
    "icd": normalize_icd,
    "checkbox": normalize_checkbox,
}


def normalize(field_type: str, raw: str) -> tuple[str | None, bool]:
    value, ok = _PROCESSORS.get(field_type, normalize_text)(raw)
    return (str(value) if value is not None else None), ok
