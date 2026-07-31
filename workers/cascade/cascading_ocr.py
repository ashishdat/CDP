"""Multi-preprocessing, multi-engine OCR candidate production.

Selection is intentionally outside this module because field validators know
whether a candidate is a valid NPI, date, ZIP code, diagnosis, and so on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from workers.page_detection.text_extraction import TextExtractor, TextLine
from workers.retry.alternate_preprocessing import (
    aggressive_contrast,
    apply_preset,
    binarize,
    sharpen,
)


@dataclass(frozen=True)
class OCRCandidatePass:
    engine: str
    preprocessing: str
    lines: list[TextLine]


class CascadingOCR:
    def __init__(self, paddle: TextExtractor, tesseract: list[TextExtractor]) -> None:
        self._paddle = paddle
        self._tesseract = tesseract

    def extract_candidates(
        self,
        image: Image.Image,
        primary_lines: list[TextLine] | None = None,
        cache_prefix: Path | None = None,
    ) -> list[OCRCandidatePass]:
        variants = [
            ("original", image),
            ("aggressive_contrast", apply_preset(image, [aggressive_contrast])),
            ("binarize_sharpen", apply_preset(image, [sharpen, binarize])),
        ]
        if image.width * image.height > 2_000_000:
            # Full-page fallbacks are expensive and the aligned source is
            # already high contrast. Keep alternate variants field-scoped.
            variants = variants[:1]
        # Paddle is the primary detector/recognizer. Alternate Paddle passes
        # are reserved for field-scoped retry; repeating full-page detection
        # for every variant is both slow and memory-heavy.
        passes = [
            OCRCandidatePass(
                "paddleocr",
                "original",
                primary_lines if primary_lines is not None else self._paddle.extract(image),
            )
        ]
        for extractor in self._tesseract:
            for name, processed in variants:
                engine = extractor.engine_name
                cache_path = (
                    cache_prefix.with_name(f"{cache_prefix.name}.{engine}.{name}.json")
                    if cache_prefix is not None
                    else None
                )
                if cache_path is not None and cache_path.is_file():
                    lines = [
                        TextLine(**item)
                        for item in json.loads(cache_path.read_text(encoding="utf-8"))
                    ]
                else:
                    lines = extractor.extract(processed)
                    if cache_path is not None:
                        cache_path.write_text(
                            json.dumps([line.__dict__ for line in lines]),
                            encoding="utf-8",
                        )
                passes.append(
                    OCRCandidatePass(
                        engine,
                        name,
                        lines,
                    )
                )
        return passes
