"""Config-driven adapters for every supported claims document family."""

from __future__ import annotations

import re
import time

from packages.domain.document import Document
from workers.field_candidates.contracts import (
    CandidateStatus,
    FieldSpec,
    PageFieldCandidate,
    PreparedPage,
)


class TextEvidenceProvider:
    family: str = ""
    provider_version = "1.0"
    model_name = "page_text"
    model_version = "1"

    @property
    def provider_name(self) -> str:
        return f"{self.family}_field_provider"

    def supports(self, page: PreparedPage, field_spec: FieldSpec) -> bool:
        return (
            not field_spec.eligible_families
            or self.family in field_spec.eligible_families
        ) and page.family_scores.get(self.family, 0.0) > 0

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
        family_confidence = page.family_scores.get(self.family, 0.0)
        if not self.supports(page, field_spec):
            return self._empty(
                document, page, field_spec, family_confidence,
                "page_not_eligible_for_family", started,
            )
        anchor_lines = [
            line for line in page.text_lines
            if any(anchor.lower() in line.text.lower() for anchor in field_spec.anchors)
        ]
        if field_spec.anchors and not anchor_lines:
            return self._empty(
                document, page, field_spec, family_confidence,
                "required_field_anchor_not_found", started,
            )
        lines = self._region_lines(page, field_spec)
        value_lines = [
            line for line in lines
            if line.text.strip()
            and not any(anchor.lower() == line.text.lower().strip()
                        for anchor in field_spec.anchors)
        ]
        if not value_lines:
            return self._empty(
                document, page, field_spec, family_confidence,
                "anchor_or_region_found_but_field_empty", started,
            )
        best = max(value_lines, key=lambda line: line.confidence)
        raw = best.text.strip()
        normalized = re.sub(r"\s+", " ", raw).strip()
        bbox = (best.x0, best.y0, best.x1, best.y1)
        return PageFieldCandidate(
            status=CandidateStatus.EVIDENCE,
            document_id=str(document.document_id),
            field_name=field_spec.field_name,
            page_number=page.page_number,
            document_family=self.family,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            raw_value=raw,
            normalized_value=normalized,
            ocr_engine="cached_full_page_ocr",
            model_name=self.model_name,
            model_version=self.model_version,
            ocr_confidence=float(best.confidence),
            family_confidence=family_confidence,
            anchor_relevance=max((line.confidence for line in anchor_lines), default=0.0),
            crop_quality=min(1.0, max(0.0, best.confidence)),
            alignment_score=page.alignment_score,
            bounding_box=bbox,
            crop_reference=None,
            hard_validation_results=("non_empty",),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    @staticmethod
    def _region_lines(page: PreparedPage, spec: FieldSpec):
        if spec.normalized_region is None:
            return list(page.text_lines)
        x0, y0, x1, y1 = spec.normalized_region
        return [
            line for line in page.text_lines
            if x0 * page.image.width <= (line.x0 + line.x1) / 2 <= x1 * page.image.width
            and y0 * page.image.height <= (line.y0 + line.y1) / 2 <= y1 * page.image.height
        ]

    def _empty(self, document, page, spec, family_confidence, reason, started):
        return PageFieldCandidate(
            status=CandidateStatus.NO_EVIDENCE,
            document_id=str(document.document_id),
            field_name=spec.field_name,
            page_number=page.page_number,
            document_family=self.family,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            raw_value=None,
            normalized_value=None,
            ocr_engine="cached_full_page_ocr",
            model_name=self.model_name,
            model_version=self.model_version,
            ocr_confidence=0.0,
            family_confidence=family_confidence,
            anchor_relevance=0.0,
            crop_quality=0.0,
            alignment_score=page.alignment_score,
            bounding_box=None,
            crop_reference=None,
            hard_validation_results=(),
            latency_ms=(time.perf_counter() - started) * 1000,
            failure_reason=reason,
        )


class PsychologicalReceiptProvider(TextEvidenceProvider):
    family = "psychological_receipt"


class CMSAttachmentProvider(TextEvidenceProvider):
    family = "cms1500_attachment"


class LaboratoryInvoiceProvider(TextEvidenceProvider):
    family = "laboratory_invoice"


class StatementProvider(TextEvidenceProvider):
    family = "insurance_statement"


class CMS1500Provider(TextEvidenceProvider):
    family = "cms1500"


class UB04Provider(TextEvidenceProvider):
    family = "ub04"


class UnknownUnstructuredProvider(TextEvidenceProvider):
    family = "unknown_unstructured"


def default_providers() -> list[TextEvidenceProvider]:
    return [
        PsychologicalReceiptProvider(),
        CMSAttachmentProvider(),
        LaboratoryInvoiceProvider(),
        StatementProvider(),
        CMS1500Provider(),
        UB04Provider(),
        UnknownUnstructuredProvider(),
    ]
