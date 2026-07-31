"""Field-crop escalation order: TrOCR, then optional compact VLM."""

from __future__ import annotations

from PIL import Image

from packages.domain.extraction import ExtractedField, FieldEvidence
from workers.unstructured_extraction.handwriting_service import HandwritingFallbackService
from workers.vlm_fallback.service import VLMFallbackService


class UnstructuredFieldEscalator:
    def __init__(
        self,
        handwriting: HandwritingFallbackService | None = None,
        vlm: VLMFallbackService | None = None,
    ) -> None:
        self._handwriting = handwriting
        self._vlm = vlm

    def collect_candidates(
        self,
        fields: list[ExtractedField],
        crop_images: dict[str, Image.Image],
        field_types: dict[str, str],
        descriptions: dict[str, str],
    ) -> dict[str, list[FieldEvidence]]:
        """Collect evidence only; the validation engine remains final arbiter."""
        candidates: dict[str, list[FieldEvidence]] = {}
        if self._handwriting is not None:
            for name, item in self._handwriting.request_for_failed_fields(
                fields, crop_images
            ).items():
                candidates.setdefault(name, []).append(item)
        if self._vlm is not None:
            # VLM service independently filters VALID fields and receives crops,
            # never full claim pages.
            for name, item in self._vlm.request_named_for_failed_fields(
                fields, crop_images, field_types, descriptions
            ).items():
                candidates.setdefault(name, []).append(item)
        return candidates
