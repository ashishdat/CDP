"""Image-based blank evidence for optional semantic table cells."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class BlankEvidence:
    is_blank: bool
    confidence: float
    ink_density: float
    substantive_components: int
    ignored_rule_components: int
    policy_version: str = "semantic-blank-v1"


def detect_semantic_blank(image: Image.Image) -> BlankEvidence:
    gray = np.asarray(image.convert("L"))
    foreground = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    substantive = ignored_rules = 0
    evidence_foreground = foreground.copy()
    height, width = gray.shape
    for component_index, (
        x, y, component_width, component_height, area
    ) in enumerate(stats[1:count], start=1):
        touches_vertical_edges = y <= 1 and y + component_height >= height - 1
        touches_horizontal_edges = x <= 1 and x + component_width >= width - 1
        is_rule = (
            touches_vertical_edges and component_width <= 4
        ) or (
            touches_horizontal_edges and component_height <= 4
        )
        if is_rule:
            ignored_rules += 1
            evidence_foreground[labels == component_index] = 0
            continue
        if (
            area >= 20
            and component_width >= 2
            and component_height >= max(10, round(height * 0.2))
        ):
            substantive += 1
    density = float(
        np.count_nonzero(evidence_foreground) / max(1, evidence_foreground.size)
    )
    is_blank = substantive == 0 and density < 0.025
    confidence = max(0.0, min(1.0, 1.0 - density / 0.025)) if is_blank else 0.0
    return BlankEvidence(is_blank, confidence, density, substantive, ignored_rules)
