"""Adapters from existing recognizers to the common field OCR protocol."""

from __future__ import annotations

import time

from packages.ocr.contracts import OCRCandidate, OCRRequest
from workers.cascade.tesseract_adapter import for_field_type
from workers.page_detection.text_extraction import TextExtractor
from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter


class RegionalTextEngine:
    def __init__(
        self,
        extractor: TextExtractor,
        engine_name: str,
        model_name: str,
        model_version: str,
    ) -> None:
        self._extractor = extractor
        self._engine_name = engine_name
        self._model_name = model_name
        self._model_version = model_version

    @property
    def engine_name(self) -> str:
        return self._engine_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    def recognize(self, request: OCRRequest) -> list[OCRCandidate]:
        started = time.monotonic()
        lines = self._extractor.extract(request.image)
        ordered = sorted(lines, key=lambda line: (line.y0, line.x0))
        raw = " ".join(line.text for line in ordered)
        confidence = (
            sum(line.confidence for line in ordered) / len(ordered) if ordered else 0.0
        )
        return [
            OCRCandidate(
                value=raw or None,
                raw_value=raw,
                engine=self.engine_name,
                model_name=self.model_name,
                model_version=self.model_version,
                preprocessing_variant="original",
                raw_confidence=confidence if raw else 0.0,
                calibrated_confidence=None,
                bounding_box=request.bounding_box,
                latency_ms=(time.monotonic() - started) * 1000,
            )
        ]


class FieldTesseractEngine(RegionalTextEngine):
    def __init__(self, field_type: str, language: str = "eng") -> None:
        extractor = for_field_type(field_type, language)
        super().__init__(
            extractor,
            extractor.engine_name,
            extractor.model_name,
            extractor.model_version,
        )


class TrOCRFieldEngine:
    def __init__(self, adapter: TrOCRAdapter) -> None:
        self._adapter = adapter

    @property
    def engine_name(self) -> str:
        return "trocr"

    @property
    def model_name(self) -> str:
        return str(self._adapter.model_name or "unconfigured")

    @property
    def model_version(self) -> str:
        return "transformers"

    def recognize(self, request: OCRRequest) -> list[OCRCandidate]:
        started = time.monotonic()
        try:
            result = self._adapter.recognize(request.image)
        except RuntimeError:
            return []
        return [
            OCRCandidate(
                value=None if result.insufficient_evidence else result.text,
                raw_value=result.text or "",
                engine=self.engine_name,
                model_name=self.model_name,
                model_version=self.model_version,
                preprocessing_variant="original",
                raw_confidence=result.confidence,
                calibrated_confidence=None,
                bounding_box=request.bounding_box,
                latency_ms=(time.monotonic() - started) * 1000,
            )
        ]
