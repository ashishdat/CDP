"""Fail-closed crop-quality checks used before human labeling."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

import numpy as np
from PIL import Image


class CropQualityStatus(StrEnum):
    VALID_SINGLE_CELL = "VALID_SINGLE_CELL"
    HEADER_CELL = "HEADER_CELL"
    MULTIPLE_CELLS = "MULTIPLE_CELLS"
    CLIPPED_CONTENT = "CLIPPED_CONTENT"
    NEIGHBOR_CONTAMINATION = "NEIGHBOR_CONTAMINATION"
    INVALID_REGION = "INVALID_REGION"
    MISSING_IMAGE = "MISSING_IMAGE"
    UNUSED_ROW = "UNUSED_ROW"
    REGISTRATION_FAILED = "REGISTRATION_FAILED"
    AMBIGUOUS_GEOMETRY = "AMBIGUOUS_GEOMETRY"


def image_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_crop(
    crop_path: Path,
    bbox: tuple[int, int, int, int],
    page_size: tuple[int, int],
    *,
    expected_hash: str,
    registration_status: str,
    row_status: str,
    is_header: bool = False,
) -> tuple[CropQualityStatus, list[str]]:
    if not crop_path.exists():
        return CropQualityStatus.MISSING_IMAGE, ["crop image does not exist"]
    if image_hash(crop_path) != expected_hash:
        return CropQualityStatus.MISSING_IMAGE, ["crop hash mismatch"]
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0 or x0 < 0 or y0 < 0 or x1 > page_size[0] or y1 > page_size[1]:
        return CropQualityStatus.INVALID_REGION, ["bbox outside registered page"]
    if registration_status != "REGISTERED":
        return CropQualityStatus.REGISTRATION_FAILED, ["page registration failed"]
    if row_status == "UNUSED":
        return CropQualityStatus.UNUSED_ROW, ["row contains no service evidence"]
    if row_status == "AMBIGUOUS":
        return CropQualityStatus.AMBIGUOUS_GEOMETRY, ["complete row review required"]
    if is_header:
        return CropQualityStatus.HEADER_CELL, ["header cells cannot be labeled"]
    gray = np.asarray(Image.open(crop_path).convert("L"))
    ink = gray < 140
    edge = max(1, min(gray.shape) // 20)
    sides = {
        "LEFT_CLIPPED": ink[:, :edge].mean(),
        "RIGHT_CLIPPED": ink[:, -edge:].mean(),
        "TOP_CLIPPED": ink[:edge, :].mean(),
        "BOTTOM_CLIPPED": ink[-edge:, :].mean(),
    }
    clipped = [
        name
        for name, ratio in sides.items()
        if ratio
        > (0.06 if name in {"LEFT_CLIPPED", "RIGHT_CLIPPED"} else 0.22)
    ]
    if clipped:
        return CropQualityStatus.CLIPPED_CONTENT, clipped
    row_lines = (ink.mean(axis=1) > 0.75).mean()
    column_lines = (ink.mean(axis=0) > 0.75).mean()
    if row_lines + column_lines > 0.15:
        return CropQualityStatus.AMBIGUOUS_GEOMETRY, ["crop is mostly grid lines"]
    return CropQualityStatus.VALID_SINGLE_CELL, []
