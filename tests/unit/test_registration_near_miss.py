"""Unit tests for ratio-only near-miss registration classification."""

from __future__ import annotations

from packages.recovery.registration_near_miss import (
    assess_evidence_near_miss,
    classify_registration_gap,
    should_attempt_near_miss_boost,
)


def test_ratio_only_near_miss_detected():
    assessment = classify_registration_gap(
        rejection_reason="low_inlier_ratio",
        inlier_count=14,
        inlier_ratio=0.1111,
        coverage_ratio=0.37,
        scale_change=0.935,
        rotation_degrees=0.45,
        perspective_distortion=0.0107,
        corner_validity=True,
    )
    assert assessment.is_near_miss is True
    assert assessment.gap_class == "NEAR_MISS_INLIER_RATIO"


def test_ratio_below_floor_not_near_miss():
    assessment = classify_registration_gap(
        rejection_reason="low_inlier_ratio",
        inlier_count=10,
        inlier_ratio=0.097,
        coverage_ratio=0.20,
        scale_change=0.94,
        rotation_degrees=1.0,
        perspective_distortion=0.01,
        corner_validity=True,
    )
    assert assessment.is_near_miss is False


def test_perspective_plus_ratio_is_not_near_miss():
    assessment = classify_registration_gap(
        rejection_reason="low_inlier_ratio,unsafe_perspective_distortion",
        inlier_count=10,
        inlier_ratio=0.097,
        coverage_ratio=0.20,
        scale_change=0.94,
        rotation_degrees=1.4,
        perspective_distortion=0.044,
        corner_validity=True,
    )
    assert assessment.is_near_miss is False
    assert assessment.gap_class == "PERSPECTIVE_UNSAFE"


def test_catastrophic_transform_class():
    assessment = classify_registration_gap(
        rejection_reason=(
            "low_inlier_ratio,low_coverage,unsafe_scale_change,"
            "unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners"
        ),
        inlier_count=8,
        inlier_ratio=0.09,
        coverage_ratio=0.04,
        scale_change=0.22,
        rotation_degrees=-92.0,
        perspective_distortion=1.65,
        corner_validity=False,
    )
    assert assessment.is_near_miss is False
    assert assessment.gap_class == "CATASTROPHIC_TRANSFORM"


def test_evidence_dict_wrapper():
    evidence = {
        "rejection_reason": "low_inlier_ratio",
        "inlier_count": 10,
        "inlier_ratio": 0.1163,
        "coverage_ratio": 0.164,
        "scale_change": 0.92,
        "rotation_degrees": 0.21,
        "perspective_distortion": 0.0106,
        "corner_validity": True,
    }
    assert should_attempt_near_miss_boost(evidence) is True
    assert assess_evidence_near_miss(evidence).gap_class == "NEAR_MISS_INLIER_RATIO"
