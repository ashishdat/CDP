"""Baseline-aware geometry interpretation for form marks; OCR is never used."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class MarkDetectionResult:
    method: str
    selected_option: str | None
    option_scores: dict[str, float]
    winning_margin: float
    ambiguous: bool
    multiple_selected: bool
    failure_reason: str | None = None


def detect_option_mark(
    crop: Image.Image,
    option_interiors: dict[str, tuple[int, int, int, int]],
    *,
    blank_reference: Image.Image | None = None,
    minimum_score: float = 0.08,
    minimum_margin: float = 0.04,
    multiple_selection_threshold: float = 0.10,
    border_inset: int = 2,
) -> MarkDetectionResult:
    observed = _ink(crop)
    baseline = _ink(blank_reference) if blank_reference is not None else None
    scores = {}
    for option, (x0, y0, x1, y1) in option_interiors.items():
        box = (
            x0 + border_inset, y0 + border_inset,
            x1 - border_inset, y1 - border_inset,
        )
        observed_density = _density(observed, box)
        baseline_density = _density(baseline, box) if baseline is not None else 0.0
        scores[option] = max(0.0, observed_density - baseline_density)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return MarkDetectionResult(
            "PIXEL_MARK_DETECTION", None, scores, 0.0, True, False,
            "no_option_regions",
        )
    winner, winner_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = winner_score - runner_up
    selected = [name for name, score in ranked if score >= multiple_selection_threshold]
    multiple = len(selected) > 1 and margin < minimum_margin
    ambiguous = winner_score < minimum_score or margin < minimum_margin or multiple
    return MarkDetectionResult(
        method="PIXEL_MARK_DETECTION",
        selected_option=None if ambiguous else winner,
        option_scores=scores,
        winning_margin=margin,
        ambiguous=ambiguous,
        multiple_selected=multiple,
        failure_reason="AMBIGUOUS_MARK" if ambiguous else None,
    )


def _ink(image: Image.Image | None) -> np.ndarray | None:
    if image is None:
        return None
    gray = np.asarray(image.convert("L"))
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def _density(ink: np.ndarray | None, box: tuple[int, int, int, int]) -> float:
    if ink is None:
        return 0.0
    x0, y0, x1, y1 = box
    interior = ink[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
    return float(np.count_nonzero(interior) / interior.size) if interior.size else 0.0
