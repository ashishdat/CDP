"""Generate complete-name interpretations without dictionary correction."""

from __future__ import annotations

import re
from dataclasses import dataclass

SUFFIXES = {"JR", "SR", "II", "III", "IV"}


@dataclass(frozen=True)
class NameInterpretation:
    first: str
    middle: str
    last: str
    suffix: str
    convention: str


def interpret_complete_name(raw: str, family_convention: str | None = None) -> list[NameInterpretation]:
    text = re.sub(r"\s+", " ", raw).strip(" ,.")
    if not text:
        return []
    results = []
    if "," in text:
        last, rest = (part.strip() for part in text.split(",", 1))
        words = rest.split()
        suffix = words[-1].upper().rstrip(".") if words and words[-1].upper().rstrip(".") in SUFFIXES else ""
        if suffix:
            words = words[:-1]
        if words:
            results.append(NameInterpretation(words[0], " ".join(words[1:]), last, suffix, "LAST_FIRST"))
    words = text.replace(",", "").split()
    if len(words) >= 2:
        results.append(NameInterpretation(words[0], " ".join(words[1:-1]), words[-1], "", "FIRST_LAST"))
        results.append(NameInterpretation(words[1], " ".join(words[2:]), words[0], "", "LAST_FIRST"))
    if family_convention:
        results.sort(key=lambda item: item.convention != family_convention)
    return list(dict.fromkeys(results))
