"""Validated multi-engine OCR cascade."""

from workers.cascade.cascading_ocr import CascadingOCR, OCRCandidatePass
from workers.cascade.tesseract_adapter import TesseractTextExtractor

__all__ = ["CascadingOCR", "OCRCandidatePass", "TesseractTextExtractor"]
