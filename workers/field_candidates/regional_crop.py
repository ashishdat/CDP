"""Coordinate-frame aware crop construction with auditable transforms."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np
from PIL import Image


class CoordinateFrame(StrEnum):
    SOURCE_PAGE = "SOURCE_PAGE"
    REFERENCE_TEMPLATE = "REFERENCE_TEMPLATE"
    ALIGNED_PAGE = "ALIGNED_PAGE"
    ANCHOR_RELATIVE = "ANCHOR_RELATIVE"
    LOCAL_CROP = "LOCAL_CROP"


@dataclass(frozen=True)
class CropTransform:
    coordinate_frame: CoordinateFrame
    requested_box: tuple[float, float, float, float]
    final_source_box: tuple[int, int, int, int] | None
    homography: tuple[tuple[float, ...], ...] | None
    alignment_score: float
    crop_valid: bool
    failure_reason: str | None


@dataclass(frozen=True)
class RegionalCrop:
    image: Image.Image | None
    transform: CropTransform
    ink_ratio: float


def build_regional_crop(
    source: Image.Image,
    box: tuple[float, float, float, float],
    *,
    coordinate_frame: CoordinateFrame,
    padding: tuple[int, int, int, int] = (0, 0, 0, 0),
    reference_dimensions: tuple[int, int] | None = None,
    candidate_to_reference_homography: np.ndarray | None = None,
    alignment_score: float = 0.0,
    minimum_ink_ratio: float = 0.001,
) -> RegionalCrop:
    source_box = _source_box(
        source, box, coordinate_frame, reference_dimensions,
        candidate_to_reference_homography,
    )
    left, top, right, bottom = padding
    clamped = (
        max(0, int(source_box[0]) - left),
        max(0, int(source_box[1]) - top),
        min(source.width, int(source_box[2]) + right),
        min(source.height, int(source_box[3]) + bottom),
    )
    homography_tuple = (
        tuple(tuple(float(value) for value in row) for row in candidate_to_reference_homography)
        if candidate_to_reference_homography is not None else None
    )
    if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
        return RegionalCrop(None, CropTransform(
            coordinate_frame, box, None, homography_tuple, alignment_score,
            False, "zero_sized_crop_after_clamp",
        ), 0.0)
    crop = source.crop(clamped)
    gray = np.array(crop.convert("L"))
    ink_ratio = float(np.count_nonzero(gray < 235) / gray.size)
    if ink_ratio < minimum_ink_ratio:
        return RegionalCrop(crop, CropTransform(
            coordinate_frame, box, clamped, homography_tuple, alignment_score,
            False, "crop_is_mostly_blank",
        ), ink_ratio)
    return RegionalCrop(crop, CropTransform(
        coordinate_frame, box, clamped, homography_tuple, alignment_score,
        True, None,
    ), ink_ratio)


def _source_box(source, box, frame, reference_dimensions, homography):
    if frame in {
        CoordinateFrame.SOURCE_PAGE,
        CoordinateFrame.ANCHOR_RELATIVE,
        CoordinateFrame.LOCAL_CROP,
    }:
        return box
    if reference_dimensions is None:
        raise ValueError(f"{frame} requires reference_dimensions")
    if homography is not None:
        inverse = np.linalg.inv(homography)
        points = np.float32([
            [box[0], box[1]], [box[2], box[1]],
            [box[2], box[3]], [box[0], box[3]],
        ]).reshape(-1, 1, 2)
        transformed = cv2.perspectiveTransform(points, inverse).reshape(-1, 2)
        return (
            transformed[:, 0].min(), transformed[:, 1].min(),
            transformed[:, 0].max(), transformed[:, 1].max(),
        )
    reference_width, reference_height = reference_dimensions
    return (
        box[0] * source.width / reference_width,
        box[1] * source.height / reference_height,
        box[2] * source.width / reference_width,
        box[3] * source.height / reference_height,
    )
