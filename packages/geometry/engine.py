"""Source-only geometry composition, independently usable through Phase 1."""

from dataclasses import dataclass

from packages.extraction_pipeline.models import FeatureFlag
from packages.extraction_pipeline.registry import StageRegistration

from .models import Box, GeometryResult, Registration
from .regions import (
    align_local,
    connected_components,
    gray_image,
    refine_roi,
    safe_cell,
    text_envelope,
)
from .registration import register, transform_box


@dataclass(frozen=True)
class GeometryRequest:
    image: object
    reference_points: tuple[tuple[float, float], ...]
    source_points: tuple[tuple[float, float], ...]
    reference_roi: Box
    source_cell: Box
    reference_patch: object | None = None
    accepted_mapping: Registration | None = None


class GeometryEngine:
    """Landmarks and cell boundaries come from source structure, not answer data.

    A reference patch, when provided, must already be at source scale/orientation.
    The affine transform is evidence of geometry, not form-identity authorization.
    """

    def resolve(self, request: GeometryRequest) -> GeometryResult:
        page = gray_image(request.image)
        registration = request.accepted_mapping or register(request.reference_points, request.source_points)
        if not registration.accepted:
            return GeometryResult(
                registration, None, None, None, (), None, None, (registration.reason,)
            )
        cell = safe_cell(request.source_cell, (page.shape[1], page.shape[0]))
        mapped = transform_box(request.reference_roi, registration)
        if cell is None or mapped.intersect(cell) != mapped:
            return GeometryResult(
                registration,
                cell,
                None,
                None,
                (),
                None,
                None,
                ("REGISTERED_ROI_OUTSIDE_SAFE_CELL",),
            )
        alignment = None
        roi = mapped
        if request.reference_patch is not None:
            alignment = align_local(page, request.reference_patch, roi, cell)
            if not alignment.accepted:
                return GeometryResult(
                    registration, cell, roi, alignment, (), None, None, (alignment.reason,)
                )
            roi = alignment.box
        components = connected_components(page, roi)
        envelope = text_envelope(components)
        refined = refine_roi(envelope, cell)
        return GeometryResult(
            registration,
            cell,
            roi,
            alignment,
            components,
            envelope,
            refined,
            ("GEOMETRY_RESOLVED",) if envelope else ("NO_FOREGROUND",),
        )

    def stage(self, legacy):
        """Pair this engine with a caller-owned legacy callable for flag rollback."""

        def replacement(payload, context):
            return self.resolve(payload)

        return StageRegistration("geometry", legacy, replacement, FeatureFlag.GEOMETRY_V3)
