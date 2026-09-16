"""Registration lineage-precheck bypass and orientation trail tests."""

from __future__ import annotations

from packages.recovery.registration_near_miss import (
    should_attempt_orientation_recovery_any,
)


def test_orientation_trail_ignores_later_lineage_mismatch():
    catastrophic = {
        "rejection_reason": (
            "low_inlier_ratio,unsafe_rotation,unsafe_perspective_distortion,"
            "invalid_transformed_corners"
        ),
        "inlier_count": 8,
        "inlier_ratio": 0.09,
        "coverage_ratio": 0.10,
        "scale_change": 1.2,
        "rotation_degrees": -165.0,
        "perspective_distortion": 1.2,
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
    assert should_attempt_orientation_recovery_any([catastrophic, lineage]) is True


def test_lineage_bypass_attempt_name_in_register_source():
    """Guard: ops ladder must offer LINEAGE_PRECHECK_BYPASS after primary lineage miss."""
    from pathlib import Path

    src = Path("app.py").read_text(encoding="utf-8")
    assert "LINEAGE_PRECHECK_BYPASS" in src
    assert "enforce_compatibility_precheck=False" in src
    assert "orientation_recovery_early" in src
    assert "bypass_lineage_precheck" in src
