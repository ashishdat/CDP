"""Fail-closed handwritten OCR escalation for invalid field crops."""

from __future__ import annotations

from PIL import Image

from packages.domain.enums import ExtractionMethod, ValidationStatus
from packages.domain.extraction import ExtractedField, FieldEvidence
from workers.cascade.handwriting_detection import HandwritingDetection, WritingType
from workers.unstructured_extraction.trocr_adapter import HandwritingRecognizer

RETRYABLE_STATUSES = (ValidationStatus.INVALID, ValidationStatus.NEEDS_REVIEW)


class HandwritingFallbackService:
    def __init__(
        self,
        recognizer: HandwritingRecognizer,
        model_name: str,
        model_version: str,
    ) -> None:
        self._recognizer = recognizer
        self._model_name = model_name
        self._model_version = model_version

    def request_for_failed_fields(
        self,
        fields: list[ExtractedField],
        crop_images: dict[str, Image.Image],
        detections: dict[str, HandwritingDetection] | None = None,
    ) -> dict[str, FieldEvidence]:
        evidence: dict[str, FieldEvidence] = {}
        selected: list[tuple[ExtractedField, Image.Image]] = []
        for field in fields:
            if field.validation_status not in RETRYABLE_STATUSES:
                continue
            crop = crop_images.get(field.field_name)
            if crop is None:
                continue
            detection = (detections or {}).get(field.field_name)
            if detection and detection.writing_type not in {
                WritingType.HANDWRITTEN, WritingType.MIXED
            }:
                continue
            selected.append((field, crop))
        if not selected:
            return evidence
        try:
            results = self._recognizer.recognize_batch([crop for _, crop in selected])
        except RuntimeError:
            return evidence  # no checkpoint/runtime: next route remains available
        for (field, _), result in zip(selected, results, strict=True):
            if result.insufficient_evidence or result.text is None:
                continue
            evidence[field.field_name] = FieldEvidence(
                source=ExtractionMethod.TROCR,
                raw_text=result.text,
                confidence=result.confidence,
                model_name=self._model_name,
                model_version=self._model_version,
            )
        return evidence
