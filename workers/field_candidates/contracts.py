"""The single candidate-provider contract used by every document family."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from PIL import Image

from packages.domain.document import Document
from workers.page_detection.text_extraction import TextLine


class CandidateStatus(StrEnum):
    EVIDENCE = "EVIDENCE"
    NO_EVIDENCE = "NO_EVIDENCE"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True)
class PreparedPage:
    page_number: int
    image: Image.Image
    image_sha256: str
    text_lines: tuple[TextLine, ...] = ()
    family_scores: dict[str, float] = field(default_factory=dict)
    alignment_score: float = 0.0


@dataclass(frozen=True)
class FieldSpec:
    field_name: str
    field_type: str
    critical: bool
    anchors: tuple[str, ...] = ()
    eligible_families: tuple[str, ...] = ()
    normalized_region: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PageFieldCandidate:
    status: CandidateStatus
    document_id: str
    field_name: str
    page_number: int
    document_family: str
    provider_name: str
    provider_version: str
    raw_value: str | None
    normalized_value: str | None
    ocr_engine: str
    model_name: str
    model_version: str
    ocr_confidence: float
    family_confidence: float
    anchor_relevance: float
    crop_quality: float
    alignment_score: float
    bounding_box: tuple[float, float, float, float] | None
    crop_reference: str | None
    hard_validation_results: tuple[str, ...]
    latency_ms: float
    failure_reason: str | None = None

    @property
    def has_evidence(self) -> bool:
        return self.status == CandidateStatus.EVIDENCE and bool(self.normalized_value)


@dataclass(frozen=True)
class FieldInferenceCompleteness:
    field_name: str
    page_count: int
    eligible_pages: int
    pages_attempted: int
    pages_with_candidates: int
    providers_expected: int
    providers_completed: int
    routing_ready: bool


class FieldCandidateProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def provider_version(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    def supports(self, page: PreparedPage, field_spec: FieldSpec) -> bool: ...

    def extract_candidates(
        self,
        document: Document,
        pages: list[PreparedPage],
        field_spec: FieldSpec,
    ) -> list[PageFieldCandidate]: ...
