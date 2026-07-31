"""Conservative, review-only alternatives for noisy table-cell OCR."""

from __future__ import annotations

import re
from datetime import datetime

OCR_CONFUSIONS = {
    "0": ("O",),
    "O": ("0",),
    "1": ("I", "L"),
    "I": ("1",),
    "L": ("1",),
    "4": ("1",),
    "8": ("B",),
    "B": ("8", "R"),
    "R": ("B",),
    "V": ("Y",),
    "Y": ("V",),
}


def parsed_alternatives(raw_value: str | None, field_type: str) -> list[dict]:
    """Return bounded alternatives with explicit lineage; never auto-acceptable."""
    raw = str(raw_value or "").strip().upper()
    if not raw:
        return []
    alternatives: dict[str, dict] = {}

    def add(value: str, method: str) -> None:
        if value and value != raw:
            alternatives.setdefault(value, {
                "value": value,
                "method": method,
                "automatically_acceptable": False,
                "reason": "AMBIGUOUS_OCR_REPAIR_REQUIRES_REVIEW",
            })

    if field_type == "date":
        digits = re.sub(r"\D", "", raw)
        widths = (6, 8)
        for width in widths:
            candidates = [digits] if len(digits) == width else []
            if len(digits) == width + 1:
                candidates.extend(digits[:index] + digits[index + 1:] for index in range(len(digits)))
            for candidate in candidates:
                formats = ("%m%d%y",) if width == 6 else ("%m%d%Y",)
                for fmt in formats:
                    try:
                        parsed = datetime.strptime(candidate, fmt)  # noqa: DTZ007
                    except ValueError:
                        continue
                    add(parsed.strftime("%m %d %y" if width == 6 else "%m %d %Y"),
                        "CALENDAR_VALIDATED_SINGLE_NOISE_DELETION")

    if field_type in {"code", "text", "integer", "numeric"}:
        compact = re.sub(r"[^A-Z0-9]", "", raw)
        for index, character in enumerate(compact):
            for replacement in OCR_CONFUSIONS.get(character, ()):
                add(
                    compact[:index] + replacement + compact[index + 1:],
                    f"SINGLE_CHARACTER_CONFUSION_{character}_TO_{replacement}",
                )
        if field_type == "code" and len(compact) <= 5:
            for index in range(1, len(compact) - 1):
                add(compact[:index] + compact[index + 1:], "SHORT_CODE_SINGLE_NOISE_DELETION")

    return list(alternatives.values())
