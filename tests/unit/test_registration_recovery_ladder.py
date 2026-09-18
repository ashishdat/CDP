"""Registration recovery ladder: authorize enhancement for geometric capture gates."""

from __future__ import annotations

from packages.recovery.diagnosis import Cause, diagnose
from packages.recovery.planner import Strategy, plan_recovery
from packages.recovery.registration_recovery import (
    decide_registration_recovery,
    enhance_for_registration,
    enhance_for_registration_contrast_stretch,
    enhance_for_registration_strong,
    should_attempt_second_preprocess,
)


def test_perspective_only_gate_gets_strong_enhancement_retry():
    decision = decide_registration_recovery(
        failure_reasons=["unsafe_perspective_distortion"],
    )
    assert decision.attempt is True
    assert decision.strategy is Strategy.ALTERNATIVE_REGISTRATION
    assert decision.cause is Cause.REGISTRATION_FAILURE


def test_low_inlier_still_gets_standard_enhancement():
    decision = decide_registration_recovery(
        failure_reasons=["low_inlier_ratio"],
    )
    assert decision.attempt is True
    assert decision.strategy is Strategy.IMAGE_ENHANCEMENT
    assert decision.cause is Cause.POOR_SCAN


def test_mixed_poor_scan_and_geometric_escalates_to_strong_enhance():
    """DJJF.010-class failures: low inliers plus perspective gates need strong enhance."""
    decision = decide_registration_recovery(
        failure_reasons=[
            "low_inlier_ratio",
            "low_coverage",
            "unsafe_perspective_distortion",
            "invalid_transformed_corners",
        ],
    )
    assert decision.attempt is True
    assert decision.strategy is Strategy.ALTERNATIVE_REGISTRATION
    assert decision.cause is Cause.POOR_SCAN


def test_diagnose_still_fails_closed_on_bare_perspective_token():
    """Mechanism tokens alone must not claim a proven physical cause."""
    diagnosis = diagnose(["unsafe_perspective_distortion"])
    assert diagnosis.primary_cause is Cause.UNDETERMINED
    plan = plan_recovery(diagnosis, strategy_available=True)
    assert plan.executable is False
    assert plan.strategy is Strategy.HUMAN_QUEUE


def test_second_preprocess_authorized_after_first_recovery_fails():
    assert should_attempt_second_preprocess(
        failure_reasons=["low_inlier_ratio", "unsafe_perspective_distortion"],
        first_recovery_attempted=True,
    )
    assert not should_attempt_second_preprocess(
        failure_reasons=["low_inlier_ratio"],
        first_recovery_attempted=False,
    )


def test_enhancement_variants_preserve_size(tmp_path):
    from PIL import Image

    img = Image.new("L", (64, 48), color=128)
    mild = enhance_for_registration(img)
    strong = enhance_for_registration_strong(img)
    stretch = enhance_for_registration_contrast_stretch(img)
    assert mild.size == img.size
    assert strong.size == img.size
    assert stretch.size == img.size
    assert mild.mode == "L"
    assert strong.mode == "L"
    assert stretch.mode == "L"
