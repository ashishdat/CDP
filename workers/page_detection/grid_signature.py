"""Grid/layout signature: a cheap, OCR-free fingerprint of a page's form
structure, used as the second escalation step (after anchor phrases) in
Bundle B's CMS-1500-page selection and as a fast pre-filter before the more
expensive template-similarity alignment step.

Approach: detect long horizontal and vertical black lines via morphological
opening (a standard technique for table/form gridline extraction), then
summarize their position/length as a fixed-length vector so two pages can
be compared with a simple correlation, independent of exact pixel offsets
from scan-to-scan skew/cropping.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

SIGNATURE_BINS = 32  # resolution of the row/column projection profile


@dataclass(frozen=True)
class GridSignature:
    row_profile: np.ndarray  # horizontal-line density per row-bin
    col_profile: np.ndarray  # vertical-line density per column-bin


def _binary_ink_mask(image: Image.Image) -> np.ndarray:
    arr = np.array(image.convert("L"))
    _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def compute_grid_signature(image: Image.Image) -> GridSignature:
    binary = _binary_ink_mask(image)
    height, width = binary.shape

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(width // 30, 1), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(height // 30, 1)))

    horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

    row_density = horizontal_lines.sum(axis=1).astype(np.float64)
    col_density = vertical_lines.sum(axis=0).astype(np.float64)

    row_profile = _bin_and_normalize(row_density, SIGNATURE_BINS)
    col_profile = _bin_and_normalize(col_density, SIGNATURE_BINS)

    return GridSignature(row_profile=row_profile, col_profile=col_profile)


def _bin_and_normalize(values: np.ndarray, n_bins: int) -> np.ndarray:
    bin_edges = np.linspace(0, len(values), n_bins + 1).astype(int)
    binned = np.array(
        [values[bin_edges[i] : bin_edges[i + 1]].sum() for i in range(n_bins)],
        dtype=np.float64,
    )
    norm = np.linalg.norm(binned)
    return binned / norm if norm > 0 else binned


def signature_similarity(a: GridSignature, b: GridSignature) -> float:
    """Cosine similarity of the concatenated row/col profiles, in [-1, 1]
    (in practice [0, 1] for these non-negative density vectors) -- 1.0 is
    an identical layout fingerprint, near 0 is an unrelated layout."""

    vec_a = np.concatenate([a.row_profile, a.col_profile])
    vec_b = np.concatenate([b.row_profile, b.col_profile])
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)
