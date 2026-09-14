"""Phase 2 geometry engine; no OCR or field-value decisions."""

from .engine import GeometryEngine, GeometryRequest
from .models import Alignment, Box, Component, GeometryResult, Registration
from .regions import align_local, connected_components, refine_roi, safe_cell, text_envelope
from .registration import register, transform_box

__all__ = [
    "Alignment",
    "Box",
    "Component",
    "GeometryEngine",
    "GeometryRequest",
    "GeometryResult",
    "Registration",
    "align_local",
    "connected_components",
    "refine_roi",
    "register",
    "safe_cell",
    "text_envelope",
    "transform_box",
]
