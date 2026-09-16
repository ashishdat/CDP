"""Unit tests for registration gap classification and recovery eligibility."""

from __future__ import annotations

from packages.recovery.registration_near_miss import (
    assess_evidence_near_miss,
    classify_registration_gap,
    content_corroboration_eligible,
    should_attempt_near_miss_boost,
    should_attempt_orientation_recovery,
    should_attempt_perspective_recovery,
)
from packages.recovery.registration_recovery import (
    enhance_for_registration_edge_deskew,
    rotate_page_for_orientation,
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


def test_strong_ratio_just_below_old_floor_is_near_miss():
    """0.09–0.10 with rich inliers/coverage is recoverable near-miss."""
    assessment = classify_registration_gap(
        rejection_reason="low_inlier_ratio",
        inlier_count=11,
        inlier_ratio=0.0982,
        coverage_ratio=0.373,
        scale_change=0.94,
        rotation_degrees=0.18,
        perspective_distortion=0.007,
        corner_validity=True,
    )
    assert assessment.is_near_miss is True


def test_weak_ratio_below_floor_not_near_miss():
    assessment = classify_registration_gap(
        rejection_reason="low_inlier_ratio",
        inlier_count=8,
        inlier_ratio=0.085,
        coverage_ratio=0.13,
        scale_change=0.94,
        rotation_degrees=1.0,
        perspective_distortion=0.01,
        corner_validity=True,
    )
    assert assessment.is_near_miss is False


def test_mild_perspective_recoverable():
    assessment = classify_registration_gap(
        rejection_reason="low_inlier_ratio,unsafe_perspective_distortion",
        inlier_count=10,
        inlier_ratio=0.097,
        coverage_ratio=0.196,
        scale_change=0.942,
        rotation_degrees=1.41,
        perspective_distortion=0.044,
        corner_validity=True,
    )
    assert assessment.is_near_miss is False
    assert assessment.is_mild_perspective is True
    assert assessment.gap_class == "PERSPECTIVE_UNSAFE"
    evidence = {
        "rejection_reason": "low_inlier_ratio,unsafe_perspective_distortion",
        "inlier_count": 10,
        "inlier_ratio": 0.097,
        "coverage_ratio": 0.196,
        "scale_change": 0.942,
        "rotation_degrees": 1.41,
        "perspective_distortion": 0.044,
        "corner_validity": True,
    }
    assert should_attempt_perspective_recovery(evidence) is True
    assert content_corroboration_eligible(evidence) is True


def test_strong_perspective_only_content_eligible():
    evidence = {
        "rejection_reason": "unsafe_perspective_distortion",
        "inlier_count": 33,
        "inlier_ratio": 0.2578,
        "coverage_ratio": 0.459,
        "scale_change": 0.95,
        "rotation_degrees": -1.45,
        "perspective_distortion": 0.0286,
        "corner_validity": True,
    }
    assert should_attempt_perspective_recovery(evidence) is True
    assert content_corroboration_eligible(evidence) is True


def test_catastrophic_orientation_candidate():
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
    assert assessment.gap_class == "CATASTROPHIC_TRANSFORM"
    assert assessment.is_orientation_candidate is True
    assert should_attempt_orientation_recovery(
        {
            "rejection_reason": assessment.reason_tokens[0]
            if False
            else (
                "low_inlier_ratio,low_coverage,unsafe_scale_change,"
                "unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners"
            ),
            "inlier_count": 8,
            "inlier_ratio": 0.09,
            "coverage_ratio": 0.04,
            "scale_change": 0.22,
            "rotation_degrees": -92.0,
            "perspective_distortion": 1.65,
            "corner_validity": False,
        }
    )


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


def test_edge_deskew_and_rotate_preserve_mode():
    from PIL import Image

    img = Image.new("L", (120, 80), color=200)
    # Draw a dark bar so border trim / deskew have structure.
    pixels = img.load()
    for x in range(10, 110):
        for y in range(30, 35):
            pixels[x, y] = 20
    deskewed = enhance_for_registration_edge_deskew(img)
    rotated = rotate_page_for_orientation(img, 180)
    assert deskewed.mode == "L"
    assert rotated.mode == "L"
    assert rotated.size[0] > 0 and rotated.size[1] > 0
