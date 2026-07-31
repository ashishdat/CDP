"""Anchor-phrase verification: the first, cheapest escalation step in page
routing (docs/ARCHITECTURE.md §9). Given OCR text lines for a page and a
template's `anchor_definitions`, decide whether the page is confidently a
genuine instance of that template.

Pure text-matching logic, decoupled from any OCR engine (see
`text_extraction.py`) -- testable with synthetic `TextLine` lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from packages.templates.models import AnchorDefinition
from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class AnchorMatchResult:
    confidence: float  # in [0, 1]; fraction of all anchors matched
    matched_phrases: list[str]
    missing_required: list[str]

    @property
    def all_required_matched(self) -> bool:
        return len(self.missing_required) == 0


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().upper())


def _region_overlaps(line: TextLine, region) -> bool:
    if region is None:
        return True
    return not (
        line.x1 < region.x0 or line.x0 > region.x1 or line.y1 < region.y0 or line.y0 > region.y1
    )


def verify_anchors(
    text_lines: list[TextLine], anchor_definitions: list[AnchorDefinition]
) -> AnchorMatchResult:
    if not anchor_definitions:
        return AnchorMatchResult(confidence=0.0, matched_phrases=[], missing_required=[])

    normalized_lines = [(_normalize(l.text), l) for l in text_lines]
    full_text = " ".join(text for text, _ in normalized_lines)

    matched: list[str] = []
    missing_required: list[str] = []

    for anchor in anchor_definitions:
        phrase = _normalize(anchor.phrase)
        if anchor.region is not None:
            scoped_text = " ".join(
                text for text, line in normalized_lines if _region_overlaps(line, anchor.region)
            )
            found = phrase in scoped_text
        else:
            found = phrase in full_text

        if found:
            matched.append(anchor.phrase)
        elif anchor.required:
            missing_required.append(anchor.phrase)

    confidence = len(matched) / len(anchor_definitions)
    return AnchorMatchResult(
        confidence=confidence, matched_phrases=matched, missing_required=missing_required
    )
