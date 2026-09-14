"""Deterministic affine registration from matched structural landmarks."""

import math

import numpy as np

from .models import Box, Registration


def register(reference_points, source_points, *, max_error: float = 2.0) -> Registration:
    """Map reference coordinates to observed source pixels without random sampling.

    Correspondences must be supplied from source structure, never field truth.
    Rejected registration carries no usable transform.
    """
    if not math.isfinite(max_error) or max_error < 0:
        raise ValueError("max_error must be finite and nonnegative")
    reference = np.asarray(reference_points, dtype=float)
    source = np.asarray(source_points, dtype=float)
    if (
        reference.ndim != 2
        or reference.shape[1:] != (2,)
        or reference.shape != source.shape
        or len(reference) < 3
        or not np.isfinite(reference).all()
        or not np.isfinite(source).all()
    ):
        return Registration(False, None, None, "INVALID_LANDMARKS")
    design = np.column_stack((reference, np.ones(len(reference))))
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(design, source, rcond=None)
    except np.linalg.LinAlgError:
        return Registration(False, None, None, "UNSTABLE_REGISTRATION")
    if rank != 3:
        return Registration(False, None, None, "DEGENERATE_LANDMARKS")
    matrix = coefficients.T
    determinant = np.linalg.det(matrix[:, :2])
    if not np.isfinite(matrix).all() or not math.isfinite(determinant) or determinant <= 1e-8:
        return Registration(False, None, None, "INVALID_TRANSFORM")
    error = float(np.max(np.linalg.norm(design @ coefficients - source, axis=1)))
    if not math.isfinite(error) or error > max_error:
        return Registration(False, None, error, "REGISTRATION_RESIDUAL_EXCEEDED")
    return Registration(
        True, tuple(tuple(float(v) for v in row) for row in matrix), error, "REGISTERED"
    )


def transform_box(box: Box, registration: Registration) -> Box:
    if not registration.accepted or registration.matrix is None:
        raise ValueError("Accepted registration is required")
    corners = np.array(
        [[box.x0, box.y0, 1], [box.x1, box.y0, 1], [box.x0, box.y1, 1], [box.x1, box.y1, 1]]
    )
    mapped = corners @ np.asarray(registration.matrix).T
    # Snap floating-point roundoff at integral coordinates before outward rounding.
    rounded = np.rint(mapped)
    mapped = np.where(np.abs(mapped - rounded) < 1e-9, rounded, mapped)
    return Box(
        math.floor(mapped[:, 0].min()),
        math.floor(mapped[:, 1].min()),
        math.ceil(mapped[:, 0].max()),
        math.ceil(mapped[:, 1].max()),
    )
