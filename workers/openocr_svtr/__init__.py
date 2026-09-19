"""OpenOCR / SVTRv2 optional printed-field OCR."""

from .adapter import (
    OpenOCRSVTRResult,
    openocr_svtr_enabled,
    recognize_openocr_svtr,
    residual_candidate_dict,
)

__all__ = [
    "OpenOCRSVTRResult",
    "openocr_svtr_enabled",
    "recognize_openocr_svtr",
    "residual_candidate_dict",
]
