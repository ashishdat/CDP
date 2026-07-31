"""Runtime orchestration that evaluates every page for every required field."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .evidence_selector import (
    FieldEvidenceDecision,
    FieldEvidenceSelector,
    PageFieldEvidence,
)


@dataclass(frozen=True)
class RequiredField:
    field_name: str
    critical: bool


class PageFieldCandidateProvider(Protocol):
    def candidates(
        self,
        *,
        document_id: str,
        page_number: int,
        field_name: str,
    ) -> list[PageFieldEvidence]: ...


@dataclass(frozen=True)
class RoutedField:
    field_name: str
    decision: FieldEvidenceDecision
    disposition: str


class FieldLevelPageRouter:
    """Search all pages independently; never reuse a document-level page choice."""

    def __init__(
        self,
        provider: PageFieldCandidateProvider,
        selector: FieldEvidenceSelector | None = None,
    ) -> None:
        self._provider = provider
        self._selector = selector or FieldEvidenceSelector()

    def route(
        self,
        *,
        document_id: str,
        page_numbers: list[int],
        required_fields: list[RequiredField],
    ) -> list[RoutedField]:
        routed: list[RoutedField] = []
        for required in required_fields:
            evidence = [
                candidate
                for page_number in page_numbers
                for candidate in self._provider.candidates(
                    document_id=document_id,
                    page_number=page_number,
                    field_name=required.field_name,
                )
            ]
            decision = self._selector.select(evidence, critical=required.critical)
            disposition = (
                "HUMAN_REVIEW_REQUIRED"
                if decision.review_required
                else "SELECTED" if decision.selected else "UNRESOLVED"
            )
            routed.append(RoutedField(required.field_name, decision, disposition))
        return routed
