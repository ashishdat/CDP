"""Azure Document Intelligence page-corner residual for catastrophic warps.

Uses configured Azure DI prebuilt-read on the full page, derives a document
quad from word/line polygons (convex hull → 4-point approx), then callers
perspective-rectify and re-run local SIFT — same Acceptance gates.

Replaces gated gpt-4o corner hints for registration escalation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np
from PIL import Image

from packages.recovery.document_quad import DocumentQuadResult, _order_corners


@dataclass(frozen=True)
class AzureDiPageCornersResult:
    attempted: bool
    configured: bool
    quad: DocumentQuadResult | None
    reason: str
    word_count: int = 0


class AzureDiPageAnalyzer(Protocol):
    def analyze_raw(self, image_bytes: bytes) -> dict[str, Any]: ...


def _polygon_points(polygon: list[float] | tuple[float, ...]) -> np.ndarray:
    pts = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
    return pts


def _collect_ink_points(payload: dict[str, Any], image_size: tuple[int, int]) -> np.ndarray:
    """Map Azure DI word/line polygons into source pixel coordinates."""
    result = payload.get("analyzeResult") or payload.get("analyze_result") or {}
    pages = result.get("pages") or []
    width_px, height_px = image_size
    points: list[np.ndarray] = []
    for page in pages:
        unit = str(page.get("unit") or "pixel").casefold()
        page_w = float(page.get("width") or 0.0) or float(width_px)
        page_h = float(page.get("height") or 0.0) or float(height_px)
        sx = width_px / page_w if page_w else 1.0
        sy = height_px / page_h if page_h else 1.0
        if unit in {"inch", "inches"}:
            # width/height already in inches; sx/sy convert to pixels.
            pass
        for group_name in ("words", "lines", "selectionMarks", "selection_marks"):
            for item in page.get(group_name) or []:
                poly = item.get("polygon") or item.get("boundingPolygon")
                if not poly or len(poly) < 8:
                    continue
                pts = _polygon_points(poly)
                pts = pts * np.array([sx, sy], dtype=np.float32)
                points.append(pts)
    if not points:
        return np.zeros((0, 2), dtype=np.float32)
    return np.concatenate(points, axis=0).astype(np.float32)


def quad_from_azure_ink_points(
    points: np.ndarray,
    *,
    image_size: tuple[int, int],
    min_area_ratio: float = 0.15,
    max_area_ratio: float = 0.95,
) -> DocumentQuadResult | None:
    """Build a document quad from Azure DI ink polygons."""
    if points is None or len(points) < 4:
        return None
    width_px, height_px = image_size
    frame_area = float(width_px * height_px)
    hull = cv2.convexHull(points.reshape(-1, 1, 2))
    peri = cv2.arcLength(hull, True)
    approx = cv2.approxPolyDP(hull, 0.02 * peri, True)
    if len(approx) == 4 and cv2.isContourConvex(approx):
        corners = _order_corners(approx)
    else:
        # Fallback: min-area rectangle of the hull.
        rect = cv2.minAreaRect(hull)
        box = cv2.boxPoints(rect)
        corners = _order_corners(box)
    area = float(cv2.contourArea(corners.reshape(-1, 1, 2)))
    ratio = area / frame_area if frame_area else 0.0
    if ratio < min_area_ratio or ratio > max_area_ratio:
        return None
    # Destination portrait page sized from quad edges.
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if width > height:
        width, height = height, width
    width = max(64, width)
    height = max(64, height)
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(corners, destination)
    # Caller supplies the gray warp; return empty rectified placeholder size.
    blank = np.full((height, width), 255, dtype=np.uint8)
    return DocumentQuadResult(
        corners=corners,
        rectified=Image.fromarray(blank),
        source_to_rectified=matrix.astype(np.float64),
        area_ratio=ratio,
        reason="AZURE_DI_PAGE_CORNERS",
    )


def run_azure_di_page_corners(
    image: Image.Image,
    *,
    settings: Any | None = None,
    analyzer: AzureDiPageAnalyzer | None = None,
) -> AzureDiPageCornersResult:
    """Invoke Azure DI and derive a page quad from text ink polygons."""
    gray = image.convert("L")
    width_px, height_px = gray.size

    if analyzer is None:
        try:
            from packages.settings import get_settings
            from workers.cascade.azure_di_factory import (
                AzureDocumentIntelligenceConfigurationError,
                azure_document_intelligence_configured,
                build_azure_read_engine,
            )
        except Exception as exc:  # noqa: BLE001
            return AzureDiPageCornersResult(
                attempted=False,
                configured=False,
                quad=None,
                reason=f"IMPORT_ERROR:{type(exc).__name__}",
            )
        cfg = settings or get_settings()
        if not azure_document_intelligence_configured(cfg):
            return AzureDiPageCornersResult(
                attempted=False,
                configured=False,
                quad=None,
                reason="AZURE_DI_NOT_CONFIGURED",
            )
        try:
            engine = build_azure_read_engine(cfg)
            backend = getattr(engine, "_backend", None)
            if backend is None or not hasattr(backend, "analyze_raw"):
                return AzureDiPageCornersResult(
                    attempted=False,
                    configured=True,
                    quad=None,
                    reason="AZURE_DI_BACKEND_NO_RAW",
                )
            analyzer = backend
        except AzureDocumentIntelligenceConfigurationError as exc:
            return AzureDiPageCornersResult(
                attempted=False,
                configured=False,
                quad=None,
                reason=f"AZURE_DI_CONFIG_ERROR:{exc}",
            )

    stream = io.BytesIO()
    gray.convert("RGB").save(stream, format="PNG")
    try:
        payload = analyzer.analyze_raw(stream.getvalue())
    except Exception as exc:  # noqa: BLE001
        return AzureDiPageCornersResult(
            attempted=True,
            configured=True,
            quad=None,
            reason=f"AZURE_DI_ERROR:{type(exc).__name__}",
        )

    points = _collect_ink_points(payload, (width_px, height_px))
    if len(points) < 4:
        return AzureDiPageCornersResult(
            attempted=True,
            configured=True,
            quad=None,
            reason="AZURE_DI_NO_INK_POLYGONS",
            word_count=0,
        )
    quad_meta = quad_from_azure_ink_points(points, image_size=(width_px, height_px))
    if quad_meta is None:
        return AzureDiPageCornersResult(
            attempted=True,
            configured=True,
            quad=None,
            reason="AZURE_DI_QUAD_REJECTED",
            word_count=len(points) // 4,
        )
    # Warp real ink into the rectified crop.
    arr = np.asarray(gray, dtype=np.uint8)
    warped = cv2.warpPerspective(
        arr,
        quad_meta.source_to_rectified,
        quad_meta.rectified.size,
        borderValue=255,
    )
    live_quad = DocumentQuadResult(
        corners=quad_meta.corners,
        rectified=Image.fromarray(warped),
        source_to_rectified=quad_meta.source_to_rectified,
        area_ratio=quad_meta.area_ratio,
        reason=quad_meta.reason,
    )
    return AzureDiPageCornersResult(
        attempted=True,
        configured=True,
        quad=live_quad,
        reason="AZURE_DI_PAGE_CORNERS_OK",
        word_count=len(points) // 4,
    )
