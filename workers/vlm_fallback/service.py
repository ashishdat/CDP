"""Ties the VLM adapter into the extraction pipeline with the two
invariants that live above the adapter itself:

- only fields that have already failed (INVALID or NEEDS_REVIEW) are ever
  sent to the VLM -- a field that's already VALID is filtered out before
  the adapter is even constructed a request for, so a validated field can
  never be overwritten by a VLM guess.
- every VLM result becomes an ordinary `FieldEvidence` (extraction_method
  = VLM_FALLBACK) and is handed back to the caller for the *same*
  `ValidationEngine` pass every other extraction method goes through --
  this module does not mark anything as final.
"""

from __future__ import annotations

import io

from PIL import Image

from packages.domain.enums import ExtractionMethod, ValidationStatus
from packages.domain.extraction import ExtractedField, FieldEvidence
from workers.vlm_fallback.adapter import VLMAdapter
from workers.vlm_fallback.schema import VLMFieldRequest

RETRYABLE_STATUSES = (ValidationStatus.INVALID, ValidationStatus.NEEDS_REVIEW)


class VLMFallbackService:
    def __init__(self, adapter: VLMAdapter, model_name: str, model_version: str) -> None:
        self._adapter = adapter
        self._model_name = model_name
        self._model_version = model_version

    def request_for_failed_fields(
        self,
        fields: list[ExtractedField],
        crop_images: dict[str, Image.Image],
        field_types: dict[str, str],
        descriptions: dict[str, str],
    ) -> list[FieldEvidence]:
        return list(
            self.request_named_for_failed_fields(
                fields, crop_images, field_types, descriptions
            ).values()
        )

    def request_named_for_failed_fields(
        self,
        fields: list[ExtractedField],
        crop_images: dict[str, Image.Image],
        field_types: dict[str, str],
        descriptions: dict[str, str],
    ) -> dict[str, FieldEvidence]:
        """Return candidates keyed by field name for escalation orchestration."""
        failed = [f for f in fields if f.validation_status in RETRYABLE_STATUSES]
        if not failed:
            return {}

        requests = [
            VLMFieldRequest(
                field_name=f.field_name,
                field_type=field_types.get(f.field_name, "text"),
                expected_description=descriptions.get(f.field_name, f.field_name),
                prior_ocr_candidates=[f.raw_value] if f.raw_value else [],
            )
            for f in failed
        ]
        failed_names = {f.field_name for f in failed}
        crops = {
            name: _encode_png(image) for name, image in crop_images.items() if name in failed_names
        }

        results = self._adapter.extract_fields(crops, requests)

        evidence: dict[str, FieldEvidence] = {}
        for result in results:
            if result.insufficient_evidence or result.value is None:
                continue  # no usable evidence -- do not fabricate a candidate
            evidence[result.field_name] = FieldEvidence(
                    source=ExtractionMethod.VLM_FALLBACK,
                    raw_text=result.value,
                    confidence=result.confidence,
                    model_name=self._model_name,
                    model_version=self._model_version,
                )
        return evidence


def _encode_png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
