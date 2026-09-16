"""Eligibility gate that keeps Docling off the standard common path.

Docling is reserved for difficult tables / itemized financial layouts when
regional OCR (Rapid→Paddle/Tesseract) cannot recover service-line structure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DoclingRouteInput:
    table_detected: bool
    template_extraction_failed: bool
    table_heavy_unstructured: bool
    regional_ocr_attempted: bool
    empty_financial_ink: bool = False
    service_line_rows_missing: bool = False
    document_category: str | None = None


_DOCLING_CATEGORIES = {
    "DIFFICULT_TABLE",
    "EOB",
    "ITEMIZED_BILL",
    "MEDICAL_INVOICE",
}


def should_run_docling(value: DoclingRouteInput) -> bool:
    """Return True only for explicit residual table / empty-finance cases."""
    category = (value.document_category or "").upper()
    if category in _DOCLING_CATEGORIES and value.regional_ocr_attempted:
        return True
    if value.table_heavy_unstructured:
        return True
    if value.empty_financial_ink and value.service_line_rows_missing and value.regional_ocr_attempted:
        return True
    return bool(
        value.table_detected
        and value.template_extraction_failed
        and value.regional_ocr_attempted
    )
