"""Conservative deterministic table-cell normalization."""

from __future__ import annotations

import re
from datetime import date

from packages.validation_rules.npi import is_valid_npi


def normalize_cell(raw: str, column: str) -> tuple[str, str, str, bool]:
    value = " ".join((raw or "").split())
    if not value:
        return "", "PRESERVE_BLANK", "VALID_BLANK", False
    lowered = column.lower()
    if "npi" in lowered:
        digits = re.sub(r"\D", "", value)
        valid = len(digits) == 10 and is_valid_npi(digits)
        return (digits if valid else value, "NPI_DIGITS", "VALID" if valid else "INVALID", valid)
    if any(token in lowered for token in ("revenue", "procedure", "diagnosis")):
        candidate = value.upper().replace(" ", "")
        valid = bool(re.fullmatch(r"[A-Z0-9.]{2,10}", candidate))
        return candidate, "CODE_CASE_SPACE", "VALID" if valid else "INVALID", valid
    if "date" in lowered:
        match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})", value)
        if match:
            month, day, year = map(int, match.groups())
            year += 2000 if year < 100 else 0
            try:
                parsed = date(year, month, day)
                return parsed.isoformat(), "VALID_DATE_ISO", "VALID", True
            except ValueError:
                pass
        return value, "VALID_DATE_ISO", "INVALID", False
    if any(token in lowered for token in ("amount", "charge", "currency")):
        match = re.fullmatch(r"\$?\s*(\d[\d,]*)(?:\.(\d{2}))?", value)
        if match:
            whole = match.group(1).replace(",", "")
            cents = match.group(2)
            normalized = f"{whole}.{cents}" if cents is not None else whole
            return normalized, "CURRENCY_EVIDENCE", "VALID", True
        return value, "CURRENCY_EVIDENCE", "INVALID", False
    return value, "WHITESPACE_ONLY", "NOT_APPLICABLE", False
