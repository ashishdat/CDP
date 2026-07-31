"""Select the best page independently for each field, never once per document."""

from __future__ import annotations

from dataclasses import dataclass

from packages.ocr.contracts import OCRCandidate


@dataclass(frozen=True)
class PageFieldEvidence:
    field_name: str
    page_number: int
    document_family: str
    candidate: OCRCandidate
    family_confidence: float
    page_relevance: float
    crop_quality: float
    hard_validation_passed: bool
    anchor_phrase: str | None = None


@dataclass(frozen=True)
class FieldEvidenceDecision:
    selected: PageFieldEvidence | None
    alternatives: tuple[PageFieldEvidence, ...]
    score: float
    reason: str
    margin: float = 0.0
    review_required: bool = False


class FieldEvidenceSelector:
    def __init__(self, minimum_score: float = 0.70, minimum_margin: float = 0.08) -> None:
        self._minimum_score = minimum_score
        self._minimum_margin = minimum_margin

    def select(
        self, evidence: list[PageFieldEvidence], *, critical: bool = False
    ) -> FieldEvidenceDecision:
        scored = [(item, self._score(item)) for item in evidence]
        valid = [
            (item, score) for item, score in scored
            if item.hard_validation_passed and item.candidate.value
        ]
        if not valid:
            return FieldEvidenceDecision(
                None, tuple(item for item, _ in scored), 0.0,
                "no_page_candidate_passed_hard_validation",
                review_required=critical,
            )
        # The margin is between pages, not providers. Multiple engines on the
        # same page strengthen that page but must not manufacture ambiguity.
        best_by_page: dict[int, tuple[PageFieldEvidence, float]] = {}
        for item, item_score in valid:
            existing = best_by_page.get(item.page_number)
            if existing is None or item_score > existing[1]:
                best_by_page[item.page_number] = (item, item_score)
        ranked = sorted(best_by_page.values(), key=lambda pair: pair[1], reverse=True)
        selected, score = ranked[0]
        runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = score - runner_up_score
        alternatives = tuple(item for item, _ in scored if item is not selected)
        if score < self._minimum_score:
            return FieldEvidenceDecision(
                None, tuple(item for item, _ in scored), score,
                "best_page_evidence_below_threshold",
                margin=margin,
                review_required=critical,
            )
        if len(ranked) > 1 and margin < self._minimum_margin:
            return FieldEvidenceDecision(
                None, tuple(item for item, _ in scored), score,
                "winning_page_margin_below_threshold",
                margin=margin,
                review_required=critical,
            )
        return FieldEvidenceDecision(
            selected, alternatives, score,
            f"selected_page_{selected.page_number}_for_{selected.field_name}",
            margin=margin,
        )

    @staticmethod
    def _score(item: PageFieldEvidence) -> float:
        confidence = (
            item.candidate.calibrated_confidence
            if item.candidate.calibrated_confidence is not None
            else item.candidate.raw_confidence
        )
        return (
            0.35 * confidence
            + 0.25 * item.family_confidence
            + 0.25 * item.page_relevance
            + 0.15 * item.crop_quality
        )
