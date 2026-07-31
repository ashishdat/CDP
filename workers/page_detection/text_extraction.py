"""OCR text extraction interface.

`paddlepaddle` (PaddleOCR's backend) has no wheel for every dev
environment (confirmed: no match for Python 3.14 on this project's host --
see docs/DATASET_FINDINGS.md-adjacent notes in docs/ARCHITECTURE.md §12),
so the real OCR engine is imported lazily and only inside the Docker image
that installs the `[ml]` extras group (Python 3.11). Everything in
`workers.page_detection`/`workers.standard_form_extraction` depends on the
`TextExtractor` protocol below, never on `paddleocr` directly, so routing
and field-processor logic is fully unit-testable with a fake.
"""

from __future__ import annotations

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


class TextExtractor(Protocol):
    def extract(self, image: Image.Image) -> list[TextLine]:
        """Full-page OCR, used for anchor-phrase verification."""
        ...

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        """Regional OCR, used by standard_form_extraction on aligned pages."""
        ...


class ModelNotAvailableError(RuntimeError):
    pass


class PaddleOCRTextExtractor:
    """Real adapter. Constructed lazily -- importing `paddleocr` at class
    definition time would make every caller of this module (including
    pure-logic unit tests) require the `[ml]` extras group installed."""

    def __init__(
        self,
        lang: str = "en",
        model_name: str = "PP-OCRv4",
        model_version: str = "paddleocr-2.x",
    ) -> None:
        self._lang = lang
        self._model_name = model_name
        self._model_version = model_version
        self._engine = None

    @property
    def engine_name(self) -> str:
        return "paddleocr"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ModelNotAvailableError(
                "paddleocr is not installed -- install the '[ml]' extras group "
                "(see pyproject.toml) or run inside the ML-enabled worker image"
            ) from exc
        self._engine = PaddleOCR(
            use_angle_cls=True,
            lang=self._lang,
            show_log=False,
            ocr_version=self._model_name,
        )
        return self._engine

    def extract(self, image: Image.Image) -> list[TextLine]:
        return self._run(image)

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        # Regional crops are the majority of OCR calls in this pipeline and
        # are cheap to upscale individually (same cost reasoning as
        # workers.retry.alternate_preprocessing's crop-scoped presets); the
        # source scans are ~200 DPI, below the ~300 DPI most OCR engines are
        # tuned for, so a modest upscale here measurably helps small-field
        # recognition. Whole-page `extract()` deliberately stays untouched --
        # that path is cost-sensitive (tests/performance/test_throughput.py).
        # Imported lazily -- `workers.retry` imports this module too
        # (retry_service depends on TextExtractor/TextLine), so a top-level
        # import here would deadlock on the circular package init.
        from workers.retry.alternate_preprocessing import UPSCALE_FACTOR, upscale

        crop = image.crop((x0, y0, x1, y1))
        upscaled = upscale(crop, UPSCALE_FACTOR)
        lines = self._run(upscaled)
        # undo the upscale, then translate crop-local coordinates back into
        # page coordinates
        return [
            TextLine(
                l.text,
                l.x0 / UPSCALE_FACTOR + x0,
                l.y0 / UPSCALE_FACTOR + y0,
                l.x1 / UPSCALE_FACTOR + x0,
                l.y1 / UPSCALE_FACTOR + y0,
                l.confidence,
            )
            for l in lines
        ]

    def _run(self, image: Image.Image) -> list[TextLine]:
        import numpy as np

        result = self._load().ocr(np.array(image.convert("RGB")), cls=True)
        lines: list[TextLine] = []
        for page in result or []:
            for box, (text, confidence) in page or []:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                lines.append(
                    TextLine(text, min(xs), min(ys), max(xs), max(ys), float(confidence))
                )
        return lines
