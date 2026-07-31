"""Geometry-preserving line segmentation for recognition-only OCR."""

from __future__ import annotations

import numpy as np
from PIL import Image


def segment_text_lines(image: Image.Image, *, minimum_ink_pixels: int = 2) -> list[Image.Image]:
    gray = np.asarray(image.convert("L"))
    active = (gray < 220).sum(axis=1) >= minimum_ink_pixels
    runs: list[tuple[int, int]] = []
    start = None
    for index, populated in enumerate(active):
        if populated and start is None:
            start = index
        elif not populated and start is not None:
            if index - start >= 3:
                runs.append((start, index))
            start = None
    if start is not None and len(active) - start >= 3:
        runs.append((start, len(active)))
    if len(runs) <= 1:
        return [image]
    return [
        image.crop((0, max(0, y0 - 2), image.width, min(image.height, y1 + 2)))
        for y0, y1 in runs
    ]
