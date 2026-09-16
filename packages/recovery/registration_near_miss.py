"""Near-miss inlier-ratio recovery — secondary matcher + content corroboration.

Does NOT soften AcceptancePolicy.min_inlier_ratio. Recovers only when:
- rejection is exactly ``low_inlier_ratio``
- absolute inliers, coverage, scale, rotation, perspective, corners all pass
- inlier_ratio sits in ``[near_miss_floor, min_inlier_ratio)``

Step 1: boosted SIFT (more features + multi-scale) must still clear full gates.
Step 2: if still ratio-only near-miss, warp + CMS landmark content check may
accept with ``NEAR_MISS_RATIO_CONTENT_CORROBORATED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Keep floor below policy min (0.12) but high enough that matches are form-like.
NEAR_MISS_INLIER_RATIO_FLOOR = 0.10
DEFAULT_MIN_INLIER_RATIO = 0.12
DEFAULT_MIN_INLIERS = 8
DEFAULT_MIN_COVERAGE = 0.12


@dataclass(frozen=True)
class NearMissAssessment:
    is_near_miss: bool
    gap_class: str
    inlier_ratio: float | None = None
    inlier_count: int | None = None
    reason_tokens: tuple[str, ...] = ()


def _tokens(rejection_reason: str | None) -> tuple[str, ...]:
    if not rejection_reason:
        return ()
    return tuple(
        part.strip()
        for part in str(rejection_reason).split(",")
        if part.strip()
    )


def _metric(evidence: Any, name: str, default=None):
    if evidence is None:
        return default
    if isinstance(evidence, dict):
        return evidence.get(name, default)
    return getattr(evidence, name, default)


def classify_registration_gap(
    *,
    rejection_reason: str | None,
    inlier_count: int | None = None,
    inlier_ratio: float | None = None,
    coverage_ratio: float | None = None,
    scale_change: float | None = None,
    rotation_degrees: float | None = None,
    perspective_distortion: float | None = None,
    corner_validity: bool | None = None,
    min_inlier_ratio: float = DEFAULT_MIN_INLIER_RATIO,
    min_inliers: int = DEFAULT_MIN_INLIERS,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    max_abs_rotation: float = 8.0,
    min_scale: float = 0.65,
    max_scale: float = 1.55,
    max_perspective: float = 0.02,
) -> NearMissAssessment:
    """Classify Track A rejection; detect recoverable ratio-only near-miss."""
    tokens = _tokens(rejection_reason)
    if not tokens:
        return NearMissAssessment(False, "NONE", inlier_ratio, inlier_count, tokens)
    token_set = set(tokens)

    unsafe = {
        "unsafe_scale_change",
        "unsafe_rotation",
        "unsafe_perspective_distortion",
        "invalid_transformed_corners",
    }
    if token_set & unsafe and (
        (scale_change is not None and not (min_scale <= float(scale_change) <= max_scale))
        or (rotation_degrees is not None and abs(float(rotation_degrees)) > max_abs_rotation)
        or (
            perspective_distortion is not None
            and float(perspective_distortion) > max_perspective
        )
        or corner_validity is False
    ):
        # Prefer catastrophic when transform is wildly broken.
        if (
            (scale_change is not None and float(scale_change) < 0.5)
            or (rotation_degrees is not None and abs(float(rotation_degrees)) > 45.0)
            or corner_validity is False
        ):
            return NearMissAssessment(
                False, "CATASTROPHIC_TRANSFORM", inlier_ratio, inlier_count, tokens
            )
        return NearMissAssessment(
            False, "PERSPECTIVE_UNSAFE", inlier_ratio, inlier_count, tokens
        )

    if token_set == {"low_inlier_ratio"}:
        ratio = float(inlier_ratio) if inlier_ratio is not None else None
        count = int(inlier_count) if inlier_count is not None else None
        coverage = float(coverage_ratio) if coverage_ratio is not None else None
        scale_ok = scale_change is None or (
            min_scale <= float(scale_change) <= max_scale
        )
        rot_ok = rotation_degrees is None or (
            abs(float(rotation_degrees)) <= max_abs_rotation
        )
        persp_ok = perspective_distortion is None or (
            float(perspective_distortion) <= max_perspective
        )
        corners_ok = corner_validity is not False
        coverage_ok = coverage is None or coverage >= min_coverage
        count_ok = count is not None and count >= min_inliers
        ratio_ok = (
            ratio is not None
            and NEAR_MISS_INLIER_RATIO_FLOOR <= ratio < min_inlier_ratio
        )
        if count_ok and ratio_ok and coverage_ok and scale_ok and rot_ok and persp_ok and corners_ok:
            return NearMissAssessment(
                True, "NEAR_MISS_INLIER_RATIO", ratio, count, tokens
            )
        if coverage is not None and coverage < min_coverage:
            return NearMissAssessment(
                False, "LOW_COVERAGE", ratio, count, tokens
            )
        if count is not None and count < min_inliers:
            return NearMissAssessment(
                False, "INSUFFICIENT_INLIERS", ratio, count, tokens
            )

    if "low_coverage" in tokens and "insufficient_inliers" in tokens:
        return NearMissAssessment(
            False, "INSUFFICIENT_INLIERS", inlier_ratio, inlier_count, tokens
        )
    if "low_coverage" in tokens:
        return NearMissAssessment(
            False, "LOW_COVERAGE", inlier_ratio, inlier_count, tokens
        )
    if "insufficient_inliers" in tokens:
        return NearMissAssessment(
            False, "INSUFFICIENT_INLIERS", inlier_ratio, inlier_count, tokens
        )
    return NearMissAssessment(
        False, "OTHER", inlier_ratio, inlier_count, tokens
    )


def assess_evidence_near_miss(evidence: Any, **policy_kwargs) -> NearMissAssessment:
    """Convenience wrapper over RegistrationEvidence or raw_evidence dict."""
    return classify_registration_gap(
        rejection_reason=_metric(evidence, "rejection_reason"),
        inlier_count=_metric(evidence, "inlier_count"),
        inlier_ratio=_metric(evidence, "inlier_ratio"),
        coverage_ratio=_metric(evidence, "coverage_ratio"),
        scale_change=_metric(evidence, "scale_change"),
        rotation_degrees=_metric(evidence, "rotation_degrees"),
        perspective_distortion=_metric(evidence, "perspective_distortion"),
        corner_validity=_metric(evidence, "corner_validity"),
        **policy_kwargs,
    )


def should_attempt_near_miss_boost(evidence: Any) -> bool:
    return assess_evidence_near_miss(evidence).is_near_miss
