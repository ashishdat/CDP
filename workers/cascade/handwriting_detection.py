"""Print/handwriting routing with a conservative OpenCV baseline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import cv2
import numpy as np
from PIL import Image


class WritingType(StrEnum):
    PRINTED = "PRINTED"
    HANDWRITTEN = "HANDWRITTEN"
    MIXED = "MIXED"
    BLANK = "BLANK"


@dataclass(frozen=True)
class HandwritingDetection:
    writing_type: WritingType
    confidence: float


class HandwritingDetector(Protocol):
    def classify(self, crop: Image.Image) -> HandwritingDetection: ...


class OpenCVHandwritingDetector:
    """Heuristic router, intentionally conservative rather than authoritative."""

    def __init__(self, minimum_confidence: float = 0.65, blank_ink_ratio: float = 0.003) -> None:
        self._minimum_confidence = minimum_confidence
        self._blank_ink_ratio = blank_ink_ratio

    def classify(self, crop: Image.Image) -> HandwritingDetection:
        gray = np.asarray(crop.convert("L"))
        binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        ink_ratio = float(np.count_nonzero(binary) / binary.size)
        if ink_ratio < self._blank_ink_ratio:
            return HandwritingDetection(WritingType.BLANK, 1.0 - ink_ratio)

        count, _, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
        components = stats[1:]
        if count <= 2 or not len(components):
            return HandwritingDetection(WritingType.MIXED, 0.0)
        heights = components[:, cv2.CC_STAT_HEIGHT].astype(float)
        widths = components[:, cv2.CC_STAT_WIDTH].astype(float)
        areas = components[:, cv2.CC_STAT_AREA].astype(float)
        keep = (areas >= 3) & (heights >= 2)
        heights, widths = heights[keep], widths[keep]
        points = centroids[1:][keep]
        if len(heights) < 3:
            return HandwritingDetection(WritingType.MIXED, 0.25)

        size_variance = min(float(np.std(heights) / max(np.mean(heights), 1)), 1.0)
        aspect_variance = min(float(np.std(widths) / max(np.mean(widths), 1)), 1.0)
        baseline_variance = min(float(np.std(points[:, 1]) / max(np.mean(heights), 1)), 1.0)
        handwriting_score = (
            0.4 * size_variance + 0.25 * aspect_variance + 0.35 * baseline_variance
        )
        distance = abs(handwriting_score - 0.5) * 2
        if distance < self._minimum_confidence:
            return HandwritingDetection(WritingType.MIXED, distance)
        writing_type = (
            WritingType.HANDWRITTEN if handwriting_score >= 0.5 else WritingType.PRINTED
        )
        return HandwritingDetection(writing_type, min(distance, 1.0))


class ClassifierHandwritingDetector:
    """Adapter for a trained classifier returning class probabilities."""

    def __init__(self, classifier) -> None:
        self._classifier = classifier

    def classify(self, crop: Image.Image) -> HandwritingDetection:
        probabilities = self._classifier.predict_proba(crop)
        label, confidence = max(probabilities.items(), key=lambda item: item[1])
        return HandwritingDetection(WritingType(label), float(confidence))
