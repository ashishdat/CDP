"""Conservative border-aware retuning for fixed-form regional crops."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class RetunedCrop:
    image: Image.Image
    inset: tuple[int, int, int, int]
    removed_rule_edges: tuple[str, ...]
    changed: bool


def retune_cell_crop(
    image: Image.Image,
    *,
    border_px: int = 16,
    maximum_inset_fraction: float = 0.22,
    rule_density: float = 0.62,
) -> RetunedCrop:
    """Remove only dense form rules near crop edges, then add white context."""
    gray = np.asarray(image.convert("L"))
    if gray.size == 0:
        return RetunedCrop(image.copy(), (0, 0, 0, 0), (), False)
    ink = gray < 160
    row_density = ink.mean(axis=1)
    column_density = ink.mean(axis=0)
    max_y = max(1, int(image.height * maximum_inset_fraction))
    max_x = max(1, int(image.width * maximum_inset_fraction))
    top = _inner_edge(row_density[:max_y], rule_density, leading=True)
    bottom_offset = _inner_edge(row_density[-max_y:], rule_density, leading=False)
    left = _inner_edge(column_density[:max_x], rule_density, leading=True)
    right_offset = _inner_edge(column_density[-max_x:], rule_density, leading=False)
    bottom = image.height - bottom_offset
    right = image.width - right_offset
    edges: list[str] = []
    if top:
        edges.append("TOP")
    if bottom_offset:
        edges.append("BOTTOM")
    if left:
        edges.append("LEFT")
    if right_offset:
        edges.append("RIGHT")
    if right - left < max(8, image.width // 3) or bottom - top < max(8, image.height // 3):
        return RetunedCrop(ImageOps.expand(image, border=border_px, fill="white"),
                           (0, 0, 0, 0), (), False)
    content = image.crop((left, top, right, bottom))
    # Remove residual one-pixel rule fragments without touching central glyphs.
    cleaned = _erase_edge_connected_rules(content)
    return RetunedCrop(ImageOps.expand(cleaned, border=border_px, fill="white"),
                       (left, top, image.width - right, image.height - bottom),
                       tuple(edges), bool(edges))


def _inner_edge(density: np.ndarray, threshold: float, *, leading: bool) -> int:
    indices = np.flatnonzero(density >= threshold)
    if not len(indices):
        return 0
    index = int(indices[-1] if leading else indices[0])
    return index + 2 if leading else len(density) - index + 1


def _erase_edge_connected_rules(image: Image.Image) -> Image.Image:
    gray = np.asarray(image.convert("L"))
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, image.width // 2), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, image.height // 2))))
    rules = cv2.bitwise_or(horizontal, vertical)
    cleaned = cv2.bitwise_and(binary, cv2.bitwise_not(rules))
    return Image.fromarray(cv2.bitwise_not(cleaned))
