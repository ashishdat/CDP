"""Detect active, unused and ambiguous fixed-form service rows."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def _ink_density(image: Image.Image) -> float:
    ink = (np.asarray(image.convert("L")) < 160).astype(np.uint8)
    # Remove continuous and dotted rules before measuring text evidence.
    ink[ink.mean(axis=1) > 0.45, :] = 0
    ink[:, ink.mean(axis=0) > 0.28] = 0
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        ink, connectivity=8
    )
    text_area = 0
    for index in range(1, count):
        _x, _y, width, height, area = stats[index]
        if area < 4 or width < 2 or height < 3:
            continue
        if height > image.height * 0.8 or width > image.width * 0.8:
            continue
        if width / height > 14 or height / width > 10:
            continue
        text_area += int(area)
    return text_area / max(1, image.width * image.height)


def classify_row(cell_crops: dict[str, Image.Image], evidence_fields: set[str]) -> dict:
    evidence = [
        {"field": name, "ink_density": _ink_density(crop)}
        for name, crop in cell_crops.items()
        if name in evidence_fields and _ink_density(crop) >= 0.008
    ]
    if len(evidence) >= 2:
        status = "ACTIVE"
    elif not evidence:
        status = "UNUSED"
    else:
        status = "AMBIGUOUS"
    return {
        "row_status": status,
        "row_evidence": evidence,
        "review_required": status == "AMBIGUOUS",
    }
