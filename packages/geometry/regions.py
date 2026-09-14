"""Pixel-only region operations; no OCR, labels, or business validators."""

import math

import cv2
import numpy as np

from .models import Alignment, Box, Component


def gray_image(image):
    array = np.asarray(image)
    if array.ndim != 2 or array.dtype != np.uint8 or not all(array.shape):
        raise ValueError("Expected a nonempty uint8 grayscale image")
    return array


def safe_cell(cell: Box, image_size: tuple[int, int], *, inset: int = 0) -> Box | None:
    width, height = image_size
    if (
        any(type(v) is not int for v in (width, height, inset))
        or min(width, height) <= 0
        or inset < 0
    ):
        raise ValueError("Invalid image dimensions or inset")
    if cell.width <= 2 * inset or cell.height <= 2 * inset:
        return None
    inner = Box(cell.x0 + inset, cell.y0 + inset, cell.x1 - inset, cell.y1 - inset)
    return inner.intersect(Box(0, 0, width, height))


def align_local(
    image, patch, roi: Box, cell: Box, *, radius: int = 14, minimum_score: float = 0.8
) -> Alignment:
    page, template = gray_image(image), gray_image(patch)
    if (
        type(radius) is not int
        or radius < 0
        or not math.isfinite(minimum_score)
        or not -1 <= minimum_score <= 1
    ):
        raise ValueError("Invalid local alignment policy")
    page_box = Box(0, 0, page.shape[1], page.shape[0])
    if cell.intersect(page_box) != cell or roi.intersect(cell) != roi:
        raise ValueError("ROI and safe cell must be inside the source image")
    if template.shape != (roi.height, roi.width):
        raise ValueError("Reference patch must have the source ROI dimensions")
    if np.ptp(template) == 0:
        return Alignment(roi, False, 0.0, "NO_REFERENCE_STRUCTURE")
    search = Box(roi.x0 - radius, roi.y0 - radius, roi.x1 + radius, roi.y1 + radius).intersect(cell)
    scores = cv2.matchTemplate(
        page[search.y0 : search.y1, search.x0 : search.x1], template, cv2.TM_CCOEFF_NORMED
    )
    finite = np.isfinite(scores)
    if not finite.any():
        return Alignment(roi, False, 0.0, "NO_LOCAL_MATCH")
    best = float(scores[finite].max())
    if best < minimum_score:
        return Alignment(roi, False, best, "LOCAL_MATCH_BELOW_THRESHOLD")
    # Ambiguous exact ties prefer smallest movement, then top-to-bottom/left-to-right.
    positions = np.argwhere(finite & (scores == best))
    y, x = min(
        positions.tolist(),
        key=lambda p: (
            (search.x0 + p[1] - roi.x0) ** 2 + (search.y0 + p[0] - roi.y0) ** 2,
            p[0],
            p[1],
        ),
    )
    x0, y0 = search.x0 + x, search.y0 + y
    return Alignment(Box(x0, y0, x0 + roi.width, y0 + roi.height), True, best, "LOCAL_ALIGNED")


def connected_components(
    image, roi: Box, *, threshold: int = 127, minimum_area: int = 1
) -> tuple[Component, ...]:
    page = gray_image(image)
    if roi.intersect(Box(0, 0, page.shape[1], page.shape[0])) != roi:
        raise ValueError("ROI must be inside the image")
    if (
        type(threshold) is not int
        or not 0 <= threshold <= 255
        or type(minimum_area) is not int
        or minimum_area < 1
    ):
        raise ValueError("Invalid component policy")
    mask = (page[roi.y0 : roi.y1, roi.x0 : roi.x1] <= threshold).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    components = []
    for i in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[i])
        if area >= minimum_area:
            components.append(
                Component(
                    Box(roi.x0 + x, roi.y0 + y, roi.x0 + x + width, roi.y0 + y + height), area
                )
            )
    return tuple(sorted(components, key=lambda c: (c.box.y0, c.box.x0, c.box.y1, c.box.x1)))


def text_envelope(components: tuple[Component, ...]) -> Box | None:
    """Foreground envelope only; does not claim components are recognized text."""
    if not components:
        return None
    return Box(
        min(c.box.x0 for c in components),
        min(c.box.y0 for c in components),
        max(c.box.x1 for c in components),
        max(c.box.y1 for c in components),
    )


def refine_roi(envelope: Box | None, cell: Box, *, padding: int = 2) -> Box | None:
    if type(padding) is not int or padding < 0:
        raise ValueError("Padding must be a nonnegative integer")
    if envelope is None:
        return None
    if envelope.intersect(cell) != envelope:
        raise ValueError("Envelope must be inside the safe cell")
    return Box(
        envelope.x0 - padding, envelope.y0 - padding, envelope.x1 + padding, envelope.y1 + padding
    ).intersect(cell)
