"""Registration gap classification — near-miss ratio + mild perspective recovery.

Does NOT soften AcceptancePolicy thresholds. Recovers only when independent
signals (boosted geometry or landmark content) clear the same gates or
corroborate a form-like warp.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Ratio-only near-miss band (policy min is 0.12).
NEAR_MISS_INLIER_RATIO_FLOOR = 0.09
NEAR_MISS_STRONG_COVERAGE = 0.20
NEAR_MISS_STRONG_INLIERS = 10
DEFAULT_MIN_INLIER_RATIO = 0.12
DEFAULT_MIN_INLIERS = 8
DEFAULT_MIN_COVERAGE = 0.12
# Mild perspective: above policy 0.02 but still form-like (not torn pages).
# Attempt ceiling allows deskew/affine retry; content corroboration stays tighter.
MILD_PERSPECTIVE_ATTEMPT_MAX = 0.20
MILD_PERSPECTIVE_CONTENT_MAX = 0.08
MILD_PERSPECTIVE_MAX = MILD_PERSPECTIVE_ATTEMPT_MAX  # classifier attempt band


@dataclass(frozen=True)
class NearMissAssessment:
    is_near_miss: bool
    gap_class: str
    inlier_ratio: float | None = None
    inlier_count: int | None = None
    reason_tokens: tuple[str, ...] = ()
    is_mild_perspective: bool = False
    is_orientation_candidate: bool = False


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


def _scale_rot_safe(
    *,
    scale_change: float | None,
    rotation_degrees: float | None,
    min_scale: float,
    max_scale: float,
    max_abs_rotation: float,
) -> bool:
    scale_ok = scale_change is None or (
        min_scale <= float(scale_change) <= max_scale
    )
    rot_ok = rotation_degrees is None or (
        abs(float(rotation_degrees)) <= max_abs_rotation
    )
    return scale_ok and rot_ok


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
    """Classify Track A rejection into recoverable vs fail-closed buckets."""
    tokens = _tokens(rejection_reason)
    if not tokens:
        return NearMissAssessment(False, "NONE", inlier_ratio, inlier_count, tokens)
    token_set = set(tokens)
    ratio = float(inlier_ratio) if inlier_ratio is not None else None
    count = int(inlier_count) if inlier_count is not None else None
    coverage = float(coverage_ratio) if coverage_ratio is not None else None
    persp = float(perspective_distortion) if perspective_distortion is not None else None

    # Orientation / catastrophic first.
    orientation = False
    if rotation_degrees is not None:
        abs_rot = abs(float(rotation_degrees))
        orientation = abs_rot >= 70.0  # ~90/180 phone capture
    # Noisy/missing rotation estimates still warrant an orientation probe when
    # Acceptance already flagged unsafe_rotation or invalid corners (classic
    # warp ladder used to drop the signal after a later lineage precheck).
    if not orientation and token_set & {
        "unsafe_rotation",
        "invalid_transformed_corners",
    }:
        if rotation_degrees is None or abs(float(rotation_degrees)) >= 35.0:
            orientation = True
    catastrophic = (
        corner_validity is False
        or (scale_change is not None and float(scale_change) < 0.5)
        or orientation
        or (persp is not None and persp > 0.5)
    )
    if catastrophic and token_set & {
        "unsafe_scale_change",
        "unsafe_rotation",
        "unsafe_perspective_distortion",
        "invalid_transformed_corners",
        "insufficient_inliers",
        "low_coverage",
        "low_inlier_ratio",
    }:
        return NearMissAssessment(
            False,
            "CATASTROPHIC_TRANSFORM",
            ratio,
            count,
            tokens,
            is_orientation_candidate=orientation,
        )

    scale_rot_ok = _scale_rot_safe(
        scale_change=scale_change,
        rotation_degrees=rotation_degrees,
        min_scale=min_scale,
        max_scale=max_scale,
        max_abs_rotation=max_abs_rotation,
    )
    corners_ok = corner_validity is not False
    coverage_ok = coverage is None or coverage >= min_coverage
    count_ok = count is not None and count >= min_inliers

    # Mild perspective: form-like warp, only perspective (optionally + ratio) soft-fail.
    mild_persp_tokens = token_set <= {
        "unsafe_perspective_distortion",
        "low_inlier_ratio",
    } and "unsafe_perspective_distortion" in token_set
    mild_persp = (
        mild_persp_tokens
        and scale_rot_ok
        and corners_ok
        and coverage_ok
        and count_ok
        and persp is not None
        and max_perspective < persp <= MILD_PERSPECTIVE_ATTEMPT_MAX
        and ratio is not None
        and ratio >= NEAR_MISS_INLIER_RATIO_FLOOR
    )
    if mild_persp:
        return NearMissAssessment(
            False,
            "PERSPECTIVE_UNSAFE",
            ratio,
            count,
            tokens,
            is_mild_perspective=True,
        )

    if token_set & {
        "unsafe_scale_change",
        "unsafe_rotation",
        "unsafe_perspective_distortion",
        "invalid_transformed_corners",
    }:
        return NearMissAssessment(
            False, "PERSPECTIVE_UNSAFE", ratio, count, tokens
        )

    if token_set == {"low_inlier_ratio"}:
        persp_ok = persp is None or persp <= max_perspective
        # Strong near-miss: slightly below floor but rich matches / coverage.
        strong = (
            count is not None
            and count >= NEAR_MISS_STRONG_INLIERS
            and coverage is not None
            and coverage >= NEAR_MISS_STRONG_COVERAGE
        )
        floor = NEAR_MISS_INLIER_RATIO_FLOOR if strong else 0.10
        ratio_ok = ratio is not None and floor <= ratio < min_inlier_ratio
        if (
            count_ok
            and ratio_ok
            and coverage_ok
            and scale_rot_ok
            and persp_ok
            and corners_ok
        ):
            return NearMissAssessment(
                True, "NEAR_MISS_INLIER_RATIO", ratio, count, tokens
            )
        if coverage is not None and coverage < min_coverage:
            return NearMissAssessment(False, "LOW_COVERAGE", ratio, count, tokens)
        if count is not None and count < min_inliers:
            return NearMissAssessment(
                False, "INSUFFICIENT_INLIERS", ratio, count, tokens
            )

    if "low_coverage" in tokens and "insufficient_inliers" in tokens:
        return NearMissAssessment(
            False, "INSUFFICIENT_INLIERS", ratio, count, tokens
        )
    if "low_coverage" in tokens:
        return NearMissAssessment(False, "LOW_COVERAGE", ratio, count, tokens)
    if "insufficient_inliers" in tokens:
        return NearMissAssessment(
            False, "INSUFFICIENT_INLIERS", ratio, count, tokens
        )
    return NearMissAssessment(False, "OTHER", ratio, count, tokens)


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


def should_attempt_near_miss_boost_any(
    evidences: list[Any] | tuple[Any, ...] | None,
) -> bool:
    """True when any ladder attempt landed in the near-miss band.

    Later enhance/lineage attempts often reclassify as CATASTROPHIC and would
    skip boost even though an earlier attempt was ratio-only near-miss
    (Independent-300 STP→REG regressions when only the latest evidence gated).
    """
    for evidence in evidences or ():
        if evidence is not None and should_attempt_near_miss_boost(evidence):
            return True
    return False


def should_attempt_perspective_recovery(evidence: Any) -> bool:
    return assess_evidence_near_miss(evidence).is_mild_perspective


def should_attempt_perspective_recovery_any(
    evidences: list[Any] | tuple[Any, ...] | None,
) -> bool:
    """True when any ladder attempt showed mild-perspective recovery signal."""
    for evidence in evidences or ():
        if evidence is not None and should_attempt_perspective_recovery(evidence):
            return True
    return False


def should_attempt_document_quad_recovery(evidence: Any) -> bool:
    """Authorize document-quad crop retry for catastrophic / multi-gate warps.

    Targets phone-framed captures where SIFT against the full frame fails with
    invalid corners / unsafe perspective / low coverage. Does not apply to
    ratio-only near-miss (handled by boost) or mild perspective (deskew path).
    """
    assessment = assess_evidence_near_miss(evidence)
    if assessment.gap_class == "CATASTROPHIC_TRANSFORM":
        return True
    # Multi-token perspective failures that never qualified as mild.
    if assessment.gap_class == "PERSPECTIVE_UNSAFE" and not assessment.is_mild_perspective:
        tokens = set(assessment.reason_tokens)
        if tokens & {
            "invalid_transformed_corners",
            "unsafe_scale_change",
            "low_coverage",
            "insufficient_inliers",
        }:
            return True
    return False


def should_attempt_learned_matcher(evidence: Any) -> bool:
    """Authorize SuperPoint+LightGlue after classical SIFT residual exhaustion."""
    return should_attempt_document_quad_recovery(evidence)


def should_attempt_azure_di_page_corners(evidence: Any) -> bool:
    """Authorize Azure DI polygon→quad residual after local / LightGlue miss."""
    return should_attempt_document_quad_recovery(evidence)


def should_attempt_orientation_recovery(evidence: Any) -> bool:
    return assess_evidence_near_miss(evidence).is_orientation_candidate


def should_attempt_orientation_recovery_any(
    evidences: list[Any] | tuple[Any, ...] | None,
) -> bool:
    """True when any ladder attempt showed an orientation-recoverable signal.

    Later template_lineage / insufficient_good_matches attempts must not erase
    an earlier catastrophic rotation signal before fail-closed.
    """
    for evidence in evidences or ():
        if evidence is not None and should_attempt_orientation_recovery(evidence):
            return True
    return False


def best_orientation_rotation_degrees(
    evidences: list[Any] | tuple[Any, ...] | None,
) -> float | None:
    """Largest-|rotation| estimate among orientation-candidate attempts."""
    best: float | None = None
    best_abs = -1.0
    for evidence in evidences or ():
        if evidence is None or not should_attempt_orientation_recovery(evidence):
            continue
        rot = _metric(evidence, "rotation_degrees")
        if rot is None:
            continue
        abs_rot = abs(float(rot))
        if abs_rot > best_abs:
            best_abs = abs_rot
            best = float(rot)
    return best


def content_corroboration_eligible(evidence: Any) -> bool:
    """Warp is form-like enough for landmark content to decide accept/reject.

    Covers ratio-only near-miss and mild-perspective cases where absolute
    inliers/coverage/scale/rotation/corners already look like a CMS page.
    """
    assessment = assess_evidence_near_miss(evidence)
    if assessment.is_near_miss:
        return True
    if assessment.is_mild_perspective:
        persp = _metric(evidence, "perspective_distortion")
        # Content accept only when perspective is modest; larger keystone must
        # clear full geometric gates after deskew/affine recovery.
        if persp is not None and float(persp) <= MILD_PERSPECTIVE_CONTENT_MAX:
            return True
        return False
    # Strong geometry that only tripped perspective: ratio already at policy.
    ratio = _metric(evidence, "inlier_ratio")
    count = _metric(evidence, "inlier_count")
    corners = _metric(evidence, "corner_validity")
    persp = _metric(evidence, "perspective_distortion")
    reason = _metric(evidence, "rejection_reason") or ""
    tokens = set(_tokens(reason))
    if (
        corners is not False
        and ratio is not None
        and float(ratio) >= DEFAULT_MIN_INLIER_RATIO
        and count is not None
        and int(count) >= DEFAULT_MIN_INLIERS
        and persp is not None
        and float(persp) <= MILD_PERSPECTIVE_CONTENT_MAX
        and tokens <= {"unsafe_perspective_distortion", "low_inlier_ratio"}
        and "unsafe_perspective_distortion" in tokens
    ):
        return True
    return False
