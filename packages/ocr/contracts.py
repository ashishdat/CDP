"""Field-level OCR request/candidate types used by every recognition engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType, FieldCriticality


@dataclass(frozen=True)
class OCRRequest:
    document_id: str
    page_number: int
    field_name: str
    field_type: str
    form_type: ClaimFormType
    image: Image.Image
    bounding_box: BoundingBox
    expected_pattern: str | None = None
    allowed_characters: str | None = None
    handwritten_probability: float = 0.0
    criticality: FieldCriticality = FieldCriticality.NON_CRITICAL


@dataclass(frozen=True)
class OCRCandidate:
    value: str | None
    raw_value: str
    engine: str
    model_name: str
    model_version: str
    preprocessing_variant: str
    raw_confidence: float
    calibrated_confidence: float | None
    bounding_box: BoundingBox
    latency_ms: float
    validation_results: tuple[str, ...] = field(default_factory=tuple)
    evidence_reference: str | None = None


class OCREngine(Protocol):
    @property
    def engine_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    def recognize(self, request: OCRRequest) -> list[OCRCandidate]: ...
