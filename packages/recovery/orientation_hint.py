"""Page orientation hints for registration recovery (before fail-closed).

Local edge-projection ranks {0,90,180,270}. Optional gated VLM (gpt-4o) may
prefer one angle when ``CDP_REGISTRATION_ORIENTATION_VLM=1`` and Azure review
is configured — never on the common path, never softens Acceptance gates.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class OrientationHint:
    degrees: int
    score: float
    source: str  # local_edge | vlm | rotation_estimate


def _as_gray(image: Image.Image) -> np.ndarray:
    arr = np.asarray(image.convert("L"), dtype=np.uint8)
    # Downscale for cheap scoring.
    h, w = arr.shape[:2]
    scale = min(1.0, 512.0 / max(h, w))
    if scale < 1.0:
        arr = cv2.resize(
            arr,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return arr


def score_orientation_edge_alignment(image: Image.Image, degrees: int) -> float:
    """Higher = more horizontal text-line energy (CMS forms are landscape-ish tall)."""
    gray = _as_gray(image)
    if degrees % 360 != 0:
        # PIL rotate is counter-clockwise; match rotate_page_for_orientation.
        rot = Image.fromarray(gray).rotate(degrees, expand=True, fillcolor=255)
        gray = np.asarray(rot, dtype=np.uint8)
    edges = cv2.Canny(gray, 60, 160)
    # Prefer strong horizontal projections (form ruled lines / text rows).
    row_energy = float(np.std(edges.mean(axis=1)))
    col_energy = float(np.std(edges.mean(axis=0)))
    # CMS portrait page: horizontal rulings dominate when upright.
    return row_energy - 0.35 * col_energy


def rank_orientation_degrees(
    image: Image.Image,
    *,
    candidates: tuple[int, ...] = (0, 180, 90, 270),
    prefer_degrees: int | None = None,
) -> list[OrientationHint]:
    """Rank candidate rotations; optional prefer_degrees floats to the front."""
    scored = [
        OrientationHint(
            degrees=d % 360,
            score=score_orientation_edge_alignment(image, d),
            source="local_edge",
        )
        for d in candidates
    ]
    scored.sort(key=lambda h: h.score, reverse=True)
    if prefer_degrees is None:
        return scored
    prefer = int(prefer_degrees) % 360
    preferred = [h for h in scored if h.degrees == prefer]
    rest = [h for h in scored if h.degrees != prefer]
    if preferred:
        top = OrientationHint(prefer, preferred[0].score, preferred[0].source)
        return [top, *rest]
    return [
        OrientationHint(prefer, 0.0, "rotation_estimate"),
        *scored,
    ]


def rotation_estimate_to_degrees(rotation_degrees: float | None) -> int | None:
    """Map noisy homography rotation to nearest cardinal undo angle."""
    if rotation_degrees is None:
        return None
    abs_rot = abs(float(rotation_degrees))
    if abs_rot < 35.0:
        return None
    # Undo observed rotation by rotating the page the opposite way.
    # Observed −165° ≈ upside-down → try 180; −90 → try 90, etc.
    nearest = int(round(abs_rot / 90.0)) * 90
    nearest = nearest % 360
    if nearest == 0:
        nearest = 180 if abs_rot >= 135 else 90
    return nearest


def orientation_vlm_enabled() -> bool:
    return (os.environ.get("CDP_REGISTRATION_ORIENTATION_VLM") or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def maybe_vlm_orientation_degrees(
    image: Image.Image,
    *,
    invoker: Callable[[Image.Image], int | None] | None = None,
) -> int | None:
    """Optional gated VLM orientation. Default invoker is a no-op unless injected."""
    if not orientation_vlm_enabled():
        return None
    if invoker is None:
        return None
    try:
        hinted = invoker(image)
    except Exception:  # noqa: BLE001 — fail closed to local ranking
        return None
    if hinted is None:
        return None
    return int(hinted) % 360


def ordered_orientation_attempts(
    image: Image.Image,
    *,
    rotation_degrees: float | None = None,
    vlm_invoker: Callable[[Image.Image], int | None] | None = None,
) -> list[int]:
    """Return non-zero rotations to try (0 is the already-tried upright page)."""
    prefer = maybe_vlm_orientation_degrees(image, invoker=vlm_invoker)
    source = "vlm" if prefer is not None else None
    if prefer is None:
        prefer = rotation_estimate_to_degrees(rotation_degrees)
        source = "rotation_estimate" if prefer is not None else None
    ranked = rank_orientation_degrees(image, prefer_degrees=prefer)
    # Skip 0° — primary/enhanced already tried the source orientation.
    ordered = [h.degrees for h in ranked if h.degrees != 0]
    # Deduplicate while preserving order.
    seen: set[int] = set()
    out: list[int] = []
    for deg in ordered:
        if deg in seen:
            continue
        seen.add(deg)
        out.append(deg)
    if source and prefer and prefer != 0 and prefer in out:
        # Already floated by rank_orientation_degrees.
        pass
    return out
