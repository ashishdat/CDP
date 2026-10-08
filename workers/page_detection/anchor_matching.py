"""Anchor-phrase verification: the first, cheapest escalation step in page
routing (docs/ARCHITECTURE.md Ã‚Â§9). Given OCR text lines for a page and a
template's `anchor_definitions`, decide whether the page is confidently a
genuine instance of that template.

Pure text-matching logic, decoupled from any OCR engine (see
`text_extraction.py`) -- testable with synthetic `TextLine` lists.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from packages.templates.models import AnchorDefinition
from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class AnchorMatchResult:
    confidence: float  # in [0, 1]; fraction of all anchors matched
    matched_phrases: list[str]
    missing_required: list[str]
    required_confidence: float | None = None

    @property
    def all_required_matched(self) -> bool:
        return len(self.missing_required) == 0


def _normalize(text: str) -> str:
    """Ignore spacing and punctuation without substituting OCR characters.

    Compact both phrases and saved OCR so split tokens (HEA LTH) compare
    identically to HEALTH. Symbols, digits and letter order remain significant.
    """
    return "".join(
        char for char in text.upper()
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _region_overlaps(line: TextLine, region) -> bool:
    if region is None:
        return True
    return not (
        line.x1 < region.x0 or line.x0 > region.x1 or line.y1 < region.y0 or line.y0 > region.y1
    )


def _nearby_phrase(phrase: str, lines: list[TextLine]) -> bool:
    """Join exact OCR fragments only when their boxes are spatial neighbours."""
    for start, line in enumerate(lines):
        pending = [(_normalize(line.text), start, frozenset({start}))]
        while pending:
            joined, previous_index, used = pending.pop()
            if phrase in joined:
                return True
            if not any(joined.endswith(phrase[:length]) for length in range(1, len(phrase))):
                continue
            if len(used) >= 6:
                continue
            previous = lines[previous_index]
            for index, following in enumerate(lines):
                if index in used:
                    continue
                height = max(previous.y1 - previous.y0, following.y1 - following.y0, 1)
                vertical_overlap = min(previous.y1, following.y1) - max(previous.y0, following.y0)
                horizontal_overlap = min(previous.x1, following.x1) - max(previous.x0, following.x0)
                same_row = vertical_overlap > 0 and 0 <= following.x0 - previous.x1 <= 3 * height
                wrapped = horizontal_overlap > 0 and 0 <= following.y0 - previous.y1 <= 2 * height
                if same_row or wrapped:
                    pending.append((joined + _normalize(following.text), index, used | {index}))
    return False


def verify_anchors(
    text_lines: list[TextLine], anchor_definitions: list[AnchorDefinition]
) -> AnchorMatchResult:
    if not anchor_definitions:
        return AnchorMatchResult(confidence=0.0, matched_phrases=[], missing_required=[])

    matched: list[str] = []
    missing_required: list[str] = []

    for anchor in anchor_definitions:
        phrase = _normalize(anchor.phrase)
        if anchor.region is not None:
            scoped_lines = [line for line in text_lines if _region_overlaps(line, anchor.region)]
            found = bool(phrase) and any(phrase in _normalize(line.text) for line in scoped_lines)
        else:
            scoped_lines = text_lines
            found = bool(phrase) and any(phrase in _normalize(line.text) for line in scoped_lines)

        if not found and phrase:
            found = _nearby_phrase(phrase, scoped_lines)

        if found:
            matched.append(anchor.phrase)
        elif anchor.required:
            missing_required.append(anchor.phrase)

    confidence = len(matched) / len(anchor_definitions)
    required = [anchor for anchor in anchor_definitions if anchor.required]
    required_confidence = ((len(required) - len(missing_required)) / len(required)
                           if required else confidence)
    return AnchorMatchResult(
        confidence=confidence, matched_phrases=matched, missing_required=missing_required,
        required_confidence=required_confidence,
    )
