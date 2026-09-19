"""Complex table residual: PaddleOCR-VL + MonkeyOCR (REVIEW_ONLY)."""

from .adapter import (
    ComplexTableResult,
    complex_tables_enabled,
    recognize_complex_table,
)

__all__ = [
    "ComplexTableResult",
    "complex_tables_enabled",
    "recognize_complex_table",
]
