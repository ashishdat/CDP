"""Config-driven document-family and relevant-page routing."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class FamilyPageDecision:
    family: str | None
    page_number: int | None
    score: float
    matched_anchors: tuple[str, ...]
    needs_review: bool


class DocumentFamilyRouter:
    def __init__(self, config: dict, minimum_score: float = 0.42) -> None:
        self._families = config["families"]
        self._minimum_score = minimum_score

    @classmethod
    def from_yaml(cls, path: Path) -> DocumentFamilyRouter:
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    def route(self, pages: dict[int, list[TextLine]]) -> FamilyPageDecision:
        best = FamilyPageDecision(None, None, 0.0, (), True)
        for page_number, lines in pages.items():
            text = " ".join(line.text.lower() for line in lines)
            for family, spec in self._families.items():
                anchors = tuple(spec.get("required_any", []))
                similarities = [
                    _phrase_score(anchor.lower(), text) for anchor in anchors
                ]
                matched = tuple(
                    anchor for anchor, score in zip(anchors, similarities, strict=True)
                    if score >= 0.55
                )
                score = max(similarities, default=0.0) + min(len(matched), 2) * 0.12
                if score > best.score:
                    best = FamilyPageDecision(
                        family, page_number, min(score, 1.0), matched, score < self._minimum_score
                    )
        return best


def _phrase_score(anchor: str, page_text: str) -> float:
    if anchor in page_text:
        return 1.0
    anchor_words = anchor.split()
    page_words = page_text.split()
    if not anchor_words or not page_words:
        return 0.0
    width = len(anchor_words)
    return max(
        (
            SequenceMatcher(None, anchor, " ".join(page_words[index:index + width])).ratio()
            for index in range(max(len(page_words) - width + 1, 1))
        ),
        default=0.0,
    )
