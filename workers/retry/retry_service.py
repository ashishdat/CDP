"""Retries OCR on exactly one failed field's crop, trying each alternate
preprocessing preset in turn and keeping whichever result has the highest
confidence -- including the possibility that none of them beat the
original. Never touches other fields or re-processes the whole page.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from workers.page_detection.text_extraction import TextExtractor, TextLine
from workers.retry.alternate_preprocessing import PRESETS, apply_preset


@dataclass(frozen=True)
class RetryResult:
    improved: bool
    preset_name: str | None
    text: str
    confidence: float


def retry_field(
    page_image: Image.Image,
    region: tuple[int, int, int, int],
    text_extractor: TextExtractor,
    original_confidence: float,
) -> RetryResult:
    x0, y0, x1, y1 = region
    crop = page_image.crop((x0, y0, x1, y1))

    best_text = ""
    best_confidence = original_confidence
    best_preset: str | None = None

    for preset_name, steps in PRESETS:
        processed = apply_preset(crop, steps)
        lines = text_extractor.extract(processed)
        if not lines:
            continue
        text, confidence = _combine_lines(lines)
        if confidence > best_confidence:
            best_text, best_confidence, best_preset = text, confidence, preset_name

    return RetryResult(
        improved=best_preset is not None,
        preset_name=best_preset,
        text=best_text,
        confidence=best_confidence,
    )


def _combine_lines(lines: list[TextLine]) -> tuple[str, float]:
    ordered = sorted(lines, key=lambda l: (l.y0, l.x0))
    text = " ".join(l.text for l in ordered)
    avg_confidence = sum(l.confidence for l in ordered) / len(ordered)
    return text, avg_confidence
