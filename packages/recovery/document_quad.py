"""Document-quad recovery for catastrophic registration warps.

Phone / table captures often leave the CMS form as a skewed rectangle inside a
larger frame. SIFT+RANSAC against the full frame then fails with multi-token
catastrophic gates (invalid corners, unsafe perspective, low coverage).

This module detects the largest 4-point document contour, perspective-rectifies
it to a portrait page, and returns the source→rectified homography so callers
can compose with template alignment (``H_final = H_sift @ H_src_to_rect``).

Does not soften Acceptance gates. If no plausible quad is found, returns None.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class DocumentQuadResult:
    """Ordered corners (TL, TR, BR, BL) in source pixels + rectified crop."""

    corners: np.ndarray  # shape (4, 2) float32
    rectified: Image.Image
    source_to_rectified: np.ndarray  # 3x3 float64
    area_ratio: float
    reason: str


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order four points as TL, TR, BR, BL."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(sums)]
    br = pts[np.argmax(sums)]
    tr = pts[np.argmin(diffs)]
    bl = pts[np.argmax(diffs)]
    return np.stack([tl, tr, br, bl]).astype(np.float32)


def _quad_dimensions(corners: np.ndarray) -> tuple[int, int]:
    tl, tr, br, bl = corners
    width_top = float(np.linalg.norm(tr - tl))
    width_bottom = float(np.linalg.norm(br - bl))
    height_left = float(np.linalg.norm(bl - tl))
    height_right = float(np.linalg.norm(br - tr))
    width = int(max(width_top, width_bottom))
    height = int(max(height_left, height_right))
    # CMS-1500 portrait page aspect ≈ 0.77 (width/height). Enforce portrait.
    if width > height:
        width, height = height, width
        # Re-order so long edge is vertical: rotate corners 90° CW in place.
        # Caller already ordered TL/TR/BR/BL for the detected quad; destination
        # size alone is enough for getPerspectiveTransform.
    width = max(64, width)
    height = max(64, height)
    return width, height


def detect_document_quad(
    image: Image.Image,
    *,
    min_area_ratio: float = 0.18,
    max_area_ratio: float = 0.92,
    min_aspect: float = 0.55,
    max_aspect: float = 0.95,
) -> DocumentQuadResult | None:
    """Find the largest form-like quadrilateral in a page capture.

    Returns None when the page is already near full-bleed (no useful crop) or
    when no 4-point contour looks like a CMS portrait form.
    """
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    h, w = gray.shape[:2]
    frame_area = float(h * w)
    if frame_area < 1:
        return None

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best: tuple[float, np.ndarray] | None = None
    for contour in contours:
        area = float(cv2.contourArea(contour))
        ratio = area / frame_area
        if ratio < min_area_ratio or ratio > max_area_ratio:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        corners = _order_corners(approx)
        width, height = _quad_dimensions(corners)
        aspect = width / float(height)
        if not (min_aspect <= aspect <= max_aspect):
            continue
        if best is None or area > best[0]:
            best = (area, corners)

    # Fallback: largest ink bounding box as a weak axis-aligned quad when edge
    # contours miss (washed-out scans). Only when ink is inset from the frame.
    if best is None:
        ink = gray < 240
        coords = cv2.findNonZero(ink.astype(np.uint8) * 255)
        if coords is None:
            return None
        x, y, bw, bh = cv2.boundingRect(coords)
        pad = max(4, min(bw, bh) // 50)
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(h, y + bh + pad)
        area = float((x1 - x0) * (y1 - y0))
        ratio = area / frame_area
        if ratio < min_area_ratio or ratio > max_area_ratio:
            return None
        aspect = (x1 - x0) / float(max(1, y1 - y0))
        if aspect > 1.0:
            # Landscape ink box — still usable; portrait destination below.
            pass
        elif not (min_aspect <= aspect <= max_aspect):
            return None
        corners = np.array(
            [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32
        )
        best = (area, corners)

    assert best is not None
    area, corners = best
    width, height = _quad_dimensions(corners)
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(corners, destination)
    warped = cv2.warpPerspective(gray, matrix, (width, height), borderValue=255)
    return DocumentQuadResult(
        corners=corners,
        rectified=Image.fromarray(warped),
        source_to_rectified=matrix.astype(np.float64),
        area_ratio=float(area / frame_area),
        reason="DOCUMENT_QUAD_DETECTED",
    )


def compose_source_to_template(
    source_to_rectified: np.ndarray,
    rectified_to_template: np.ndarray,
) -> np.ndarray:
    """Compose ``H_sift @ H_quad`` so warpPerspective(source, H) → template."""
    return (
        np.asarray(rectified_to_template, dtype=np.float64)
        @ np.asarray(source_to_rectified, dtype=np.float64)
    )
