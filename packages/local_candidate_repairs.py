"""Conservative deterministic repairs for constrained local OCR candidates."""

from __future__ import annotations

import re

_LABELS = re.compile(r"\b(?:PATIENT|ADDRESS|CITY|STATE|ZIP|INSURED)\b", re.IGNORECASE)
_STREET_SUFFIX = re.compile(r"\b(?:STREET|ST|ROAD|RD|AVENUE|AVE|LANE|LN|DRIVE|DR)\b")


def clean_city_candidate(raw: str) -> str | None:
    value = re.sub(r"[^A-Za-z .'-]", " ", raw).strip(" .'-").upper()
    value = re.sub(r"\s+", " ", value)
    if not value or _LABELS.search(value) or not re.fullmatch(r"[A-Z][A-Z .'-]{1,}", value):
        return None
    return value


def repair_handwritten_address(raw: str) -> str | None:
    """Repair one OCR-confused house-number glyph without inventing street text."""
    value = raw.upper().strip()
    match = re.match(r"^\s*([0-9]{2,7})([()]?)\s+(.+?)\s*$", value)
    if not match:
        return None
    digits, confused_tail, street = match.groups()
    # A single terminal parenthesis is a common digit-2 recognizer confusion.
    # It is eligible only after at least two visible digits and before a valid
    # independently transcribed street phrase.
    if confused_tail:
        digits += "2"
    street = re.sub(r"\s+[.|]\s*\d+\s*[.]?\s*$", "", street)
    street = re.sub(r"[^A-Z0-9 #.'-]", " ", street)
    street = re.sub(r"\s+", " ", street).strip(" .")
    if _LABELS.search(street) or not _STREET_SUFFIX.search(street):
        return None
    return f"{digits} {street}"
