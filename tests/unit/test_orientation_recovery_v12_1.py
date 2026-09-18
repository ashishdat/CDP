"""Tests for orientation hint ranking and widened recovery eligibility."""

from __future__ import annotations

from PIL import Image, ImageDraw

from packages.recovery.orientation_hint import (
    ordered_orientation_attempts,
    rank_orientation_degrees,
    rotation_estimate_to_degrees,
    score_orientation_edge_alignment,
)
from packages.recovery.registration_near_miss import (
    best_orientation_rotation_degrees,
    classify_registration_gap,
    should_attempt_orientation_recovery,
    should_attempt_orientation_recovery_any,
)


def _ruled_portrait(w: int = 200, h: int = 280) -> Image.Image:
    """Synthetic CMS-like page with strong horizontal rulings."""
    img = Image.new("L", (w, h), color=240)
    draw = ImageDraw.Draw(img)
    for y in range(40, h - 20, 18):
        draw.line((20, y, w - 20, y), fill=20, width=2)
    return img


def test_rotation_estimate_maps_to_cardinal():
    assert rotation_estimate_to_degrees(-165.0) == 180
    assert rotation_estimate_to_degrees(-92.0) == 90
    assert rotation_estimate_to_degrees(5.0) is None


def test_edge_rank_prefers_upright_over_sideways():
    upright = _ruled_portrait()
    ranked = rank_orientation_degrees(upright)
    assert ranked[0].degrees in {0, 180}
    # Sideways should score worse than upright for horizontal-rule pages.
    assert score_orientation_edge_alignment(upright, 0) >= score_orientation_edge_alignment(
        upright, 90
    )


def test_ordered_attempts_skip_zero_and_honor_prefer():
    img = _ruled_portrait()
    ordered = ordered_orientation_attempts(img, rotation_degrees=-170.0)
    assert 0 not in ordered
    assert ordered[0] == 180
    assert set(ordered) == {90, 180, 270}


def test_unsafe_rotation_without_large_estimate_is_orientation_candidate():
    assessment = classify_registration_gap(
        rejection_reason="low_inlier_ratio,unsafe_rotation,invalid_transformed_corners",
        inlier_count=8,
        inlier_ratio=0.09,
        coverage_ratio=0.10,
        scale_change=1.2,
        rotation_degrees=-40.0,
        perspective_distortion=0.08,
        corner_validity=False,
    )
    assert assessment.gap_class == "CATASTROPHIC_TRANSFORM"
    assert assessment.is_orientation_candidate is True


def test_orientation_trail_survives_later_lineage_mismatch():
    catastrophic = {
        "rejection_reason": (
            "low_inlier_ratio,unsafe_scale_change,unsafe_rotation,"
            "unsafe_perspective_distortion,invalid_transformed_corners"
        ),
        "inlier_count": 8,
        "inlier_ratio": 0.09,
        "coverage_ratio": 0.10,
        "scale_change": 1.79,
        "rotation_degrees": -164.9,
        "perspective_distortion": 8.65,
        "corner_validity": False,
    }
    lineage = {
        "rejection_reason": "template_lineage_mismatch",
        "inlier_count": None,
        "inlier_ratio": 0.0,
        "coverage_ratio": None,
        "scale_change": None,
        "rotation_degrees": None,
        "perspective_distortion": None,
        "corner_validity": None,
    }
    assert should_attempt_orientation_recovery(lineage) is False
    assert should_attempt_orientation_recovery_any([catastrophic, lineage]) is True
    assert best_orientation_rotation_degrees([catastrophic, lineage]) == -164.9
