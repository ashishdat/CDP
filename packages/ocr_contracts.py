"""Shared OCR contracts for packages and workers.

Keep pure data / error types here so the packages layer never depends on the
workers layer for TextLine shapes or availability errors. Concrete extractors
stay in workers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


class ModelNotAvailableError(RuntimeError):
    """Raised when an optional OCR engine dependency is not installed/configured."""


class TextExtractor(Protocol):
    def extract(self, image: Image.Image) -> list[TextLine]:
        """Full-page OCR, used for anchor-phrase verification."""
        ...

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        """Regional OCR, used by standard_form_extraction on aligned pages."""
        ...


# Callable that constructs a regional/handwriting recognizer for OCRRouter.
RecognizerFactory = Callable[[], Callable]
EngineFactoryMap = Mapping[str, RecognizerFactory]
