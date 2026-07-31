"""Optional Docling layout/OCR candidate provider.

Docling is deliberately an additive evidence source.  It does not alter page
routing, auto-accept critical names, or replace template/anchor crop logic.
The import is lazy so the core and offline test suites do not require the
large Docling model stack.
"""

from __future__ import annotations

import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from packages.domain.document import Document
from workers.field_candidates.contracts import (
    CandidateStatus,
    FieldSpec,
    PageFieldCandidate,
    PreparedPage,
)


@dataclass(frozen=True)
class DoclingText:
    text: str
    confidence: float = 0.55


class DoclingEngine(Protocol):
    version: str
    model_name: str
    model_version: str

    def extract(self, image_path: Path) -> list[DoclingText]: ...


class LocalDoclingEngine:
    """Docling standard image pipeline using its automatic local OCR backend."""

    model_name = "docling_standard_image_pipeline"
    model_version = "default"

    def __init__(self) -> None:
        try:
            from importlib.metadata import version

            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Docling is unavailable; install the 'docling' optional dependency"
            ) from exc
        self.version = version("docling")
        self._converter = DocumentConverter()

    def extract(self, image_path: Path) -> list[DoclingText]:
        result = self._converter.convert(image_path)
        extracted: list[DoclingText] = []
        # iterate_items follows the DoclingDocument reading-order tree.
        for item, _level in result.document.iterate_items():
            text = getattr(item, "text", None)
            if text and text.strip():
                extracted.append(DoclingText(text=text.strip()))
        return extracted


class DoclingCandidateProvider:
    """Generate reading-order regional evidence for selected document families."""

    provider_name = "docling_layout_ocr"
    provider_version = "1.0"
    # Start where layout reconstruction is useful; structured forms retain their
    # OpenCV/template regional pipeline.
    DEFAULT_FAMILIES = frozenset(
        {
            "laboratory_invoice",
            "insurance_statement",
            "psychological_receipt",
            "cms1500_attachment",
            "unknown_unstructured",
        }
    )

    def __init__(
        self,
        engine: DoclingEngine | None = None,
        *,
        eligible_families: frozenset[str] | None = None,
    ) -> None:
        self._engine = engine
        self._eligible_families = eligible_families or self.DEFAULT_FAMILIES

    @property
    def model_name(self) -> str:
        return self._engine.model_name if self._engine else "docling_standard_image_pipeline"

    @property
    def model_version(self) -> str:
        return self._engine.model_version if self._engine else "default"

    def supports(self, page: PreparedPage, field_spec: FieldSpec) -> bool:
        matching = self._eligible_families.intersection(page.family_scores)
        if field_spec.eligible_families:
            matching = matching.intersection(field_spec.eligible_families)
        return any(page.family_scores.get(family, 0.0) > 0 for family in matching)

    def extract_candidates(
        self,
        document: Document,
        pages: list[PreparedPage],
        field_spec: FieldSpec,
    ) -> list[PageFieldCandidate]:
        return [self._extract_page(document, page, field_spec) for page in pages]

    def _extract_page(
        self, document: Document, page: PreparedPage, field_spec: FieldSpec
    ) -> PageFieldCandidate:
        started = time.perf_counter()
        family = self._winning_family(page)
        if not self.supports(page, field_spec):
            return self._result(
                document, page, field_spec, family, started,
                status=CandidateStatus.NO_EVIDENCE,
                failure_reason="page_not_eligible_for_docling_pilot",
            )
        try:
            engine = self._engine or LocalDoclingEngine()
            crop, bbox = self._crop(page.image, field_spec.normalized_region)
            if crop.width == 0 or crop.height == 0:
                raise ValueError("zero_sized_crop")
            with tempfile.TemporaryDirectory(prefix="idp_docling_") as tmp:
                crop_path = Path(tmp) / "region.png"
                crop.save(crop_path)
                lines = engine.extract(crop_path)
        except Exception as exc:  # noqa: BLE001 - provider failure must be persisted
            return self._result(
                document, page, field_spec, family, started,
                status=CandidateStatus.PROVIDER_ERROR,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )

        text = "\n".join(line.text for line in lines if line.text.strip()).strip()
        if not text:
            return self._result(
                document, page, field_spec, family, started,
                status=CandidateStatus.NO_EVIDENCE,
                failure_reason="docling_returned_no_regional_text",
                bbox=bbox,
            )
        confidence = sum(line.confidence for line in lines) / len(lines)
        return self._result(
            document, page, field_spec, family, started,
            status=CandidateStatus.EVIDENCE,
            raw=text,
            normalized=re.sub(r"\s+", " ", text).strip(),
            confidence=confidence,
            bbox=bbox,
            validation=("non_empty", "regional_reading_order"),
        )

    def _winning_family(self, page: PreparedPage) -> str:
        eligible = {
            family: score
            for family, score in page.family_scores.items()
            if family in self._eligible_families
        }
        return max(eligible, key=eligible.get) if eligible else "unknown_unstructured"

    @staticmethod
    def _crop(
        image: Image.Image,
        region: tuple[float, float, float, float] | None,
    ) -> tuple[Image.Image, tuple[float, float, float, float]]:
        if region is None:
            bbox = (0.0, 0.0, float(image.width), float(image.height))
        else:
            x0, y0, x1, y1 = region
            bbox = (
                max(0.0, min(float(image.width), x0 * image.width)),
                max(0.0, min(float(image.height), y0 * image.height)),
                max(0.0, min(float(image.width), x1 * image.width)),
                max(0.0, min(float(image.height), y1 * image.height)),
            )
        return image.crop(tuple(round(value) for value in bbox)), bbox

    def _result(
        self,
        document: Document,
        page: PreparedPage,
        spec: FieldSpec,
        family: str,
        started: float,
        *,
        status: CandidateStatus,
        raw: str | None = None,
        normalized: str | None = None,
        confidence: float = 0.0,
        bbox: tuple[float, float, float, float] | None = None,
        validation: tuple[str, ...] = (),
        failure_reason: str | None = None,
    ) -> PageFieldCandidate:
        engine = self._engine
        return PageFieldCandidate(
            status=status,
            document_id=str(document.document_id),
            field_name=spec.field_name,
            page_number=page.page_number,
            document_family=family,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            raw_value=raw,
            normalized_value=normalized,
            ocr_engine="docling_auto_ocr",
            model_name=engine.model_name if engine else self.model_name,
            model_version=engine.model_version if engine else self.model_version,
            ocr_confidence=confidence,
            family_confidence=page.family_scores.get(family, 0.0),
            anchor_relevance=0.0,
            crop_quality=1.0 if bbox else 0.0,
            alignment_score=page.alignment_score,
            bounding_box=bbox,
            crop_reference=None,
            hard_validation_results=validation,
            latency_ms=(time.perf_counter() - started) * 1000,
            failure_reason=failure_reason,
        )
