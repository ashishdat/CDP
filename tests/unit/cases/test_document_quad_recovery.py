"""Document-quad recovery tests for catastrophic registration warps."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from packages.recovery.document_quad import (
    compose_source_to_template,
    detect_document_quad,
)
from packages.recovery.registration_near_miss import (
    classify_registration_gap,
    should_attempt_document_quad_recovery,
)
from packages.tool_escalation import EscalationTool, plan_field_escalation


def _phone_framed_form(size=(400, 600), form_box=(60, 80, 340, 520)) -> Image.Image:
    """Synthetic gray page with a darker form rectangle inset in a light frame."""
    img = Image.new("L", size, color=245)
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = form_box
    draw.rectangle([x0, y0, x1, y1], fill=220, outline=30, width=3)
    # Fake form rulings so Canny finds structure.
    for y in range(y0 + 20, y1 - 10, 18):
        draw.line([(x0 + 8, y), (x1 - 8, y)], fill=40, width=1)
    for x in range(x0 + 30, x1 - 10, 40):
        draw.line([(x, y0 + 12), (x, y1 - 12)], fill=50, width=1)
    draw.text((x0 + 40, y0 + 30), "HEALTH INSURANCE", fill=10)
    return img


def test_detect_document_quad_finds_inset_form():
    img = _phone_framed_form()
    result = detect_document_quad(img)
    assert result is not None
    assert 0.18 <= result.area_ratio <= 0.92
    assert result.rectified.size[0] > 32
    assert result.source_to_rectified.shape == (3, 3)


def test_detect_document_quad_skips_full_bleed():
    img = Image.new("L", (300, 400), color=200)
    draw = ImageDraw.Draw(img)
    draw.rectangle([2, 2, 297, 397], outline=20, width=2)
    for y in range(20, 380, 15):
        draw.line([(10, y), (290, y)], fill=30, width=1)
    result = detect_document_quad(img, max_area_ratio=0.92)
    # Full-bleed ink box exceeds max_area_ratio → no useful crop.
    assert result is None or result.area_ratio <= 0.92


def test_compose_source_to_template_orders_matrices():
    h_quad = np.eye(3, dtype=np.float64)
    h_quad[0, 2] = 10.0
    h_sift = np.eye(3, dtype=np.float64)
    h_sift[1, 2] = 5.0
    composed = compose_source_to_template(h_quad, h_sift)
    expected = h_sift @ h_quad
    assert np.allclose(composed, expected)


def test_should_attempt_document_quad_on_catastrophic():
    gap = classify_registration_gap(
        rejection_reason=(
            "low_inlier_ratio,unsafe_rotation,unsafe_perspective_distortion,"
            "invalid_transformed_corners"
        ),
        inlier_count=4,
        inlier_ratio=0.05,
        coverage_ratio=0.08,
        scale_change=0.4,
        rotation_degrees=-160.0,
        perspective_distortion=0.8,
        corner_validity=False,
    )
    assert gap.gap_class == "CATASTROPHIC_TRANSFORM"
    # Build a minimal evidence-like object
    class Ev:
        rejection_reason = gap.reason_tokens and ",".join(gap.reason_tokens)
        inlier_count = 4
        inlier_ratio = 0.05
        coverage_ratio = 0.08
        scale_change = 0.4
        rotation_degrees = -160.0
        perspective_distortion = 0.8
        corner_validity = False

    assert should_attempt_document_quad_recovery(Ev()) is True


def test_escalation_prefers_document_quad_before_hitl():
    decision = plan_field_escalation(
        gap_class="CATASTROPHIC_TRANSFORM",
        field_name="*",
    )
    assert decision.tool == EscalationTool.DOCUMENT_QUAD_RECOVERY

    after = plan_field_escalation(
        gap_class="REGISTRATION_FAILED",
        field_name="*",
        document_quad_attempted=True,
        learned_matcher_attempted=True,
        azure_di_corners_attempted=True,
    )
    assert after.tool == EscalationTool.OPENCV_REGISTRATION_HITL
