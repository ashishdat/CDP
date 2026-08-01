"""Validated multi-engine OCR cascade with lazy public exports."""

from __future__ import annotations

from typing import Any

__all__ = ["CascadingOCR", "OCRCandidatePass", "TesseractTextExtractor"]


def __getattr__(name: str) -> Any:
    if name in {"CascadingOCR", "OCRCandidatePass"}:
        from workers.cascade import cascading_ocr
        return getattr(cascading_ocr, name)
    if name == "TesseractTextExtractor":
        from workers.cascade import tesseract_adapter
        return tesseract_adapter.TesseractTextExtractor
    raise AttributeError(name)
