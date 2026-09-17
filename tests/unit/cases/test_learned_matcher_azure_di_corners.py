"""SuperPoint+LightGlue and Azure DI page-corner residual tests."""

from __future__ import annotations

import numpy as np
from PIL import Image

from packages.recovery.azure_di_page_corners import (
    quad_from_azure_ink_points,
    run_azure_di_page_corners,
)
from packages.recovery.learned_matcher import LearnedCorrespondences
from packages.tool_escalation import EscalationTool, load_secondary_policy, plan_field_escalation
from workers.page_detection.template_alignment import align_learned_matcher


class _FakeExtractor:
    def __init__(self, n: int = 64, shift_px: float = 2.0) -> None:
        self.n = n
        self.shift_px = shift_px

    def extract(self, candidate: Image.Image, reference: Image.Image):
        # Grid correspondences with pure translation → safe homography + coverage.
        xs = np.linspace(20, candidate.size[0] - 20, 8)
        ys = np.linspace(20, candidate.size[1] - 20, 8)
        xx, yy = np.meshgrid(xs, ys)
        src = np.stack([xx.ravel(), yy.ravel()], axis=1).astype(np.float32)[: self.n]
        dst = src + np.array([self.shift_px, self.shift_px], dtype=np.float32)
        return LearnedCorrespondences(
            source_xy=src,
            template_xy=dst,
            scores=np.ones(len(src), dtype=np.float32),
            reason="FAKE",
        )


def test_align_learned_matcher_accepts_safe_translation():
    cand = Image.new("L", (220, 220), color=240)
    ref = Image.new("L", (220, 220), color=240)
    result = align_learned_matcher(cand, ref, extractor=_FakeExtractor())
    assert result.homography is not None
    assert result.evidence is not None
    assert result.evidence.algorithm == "superpoint_lightglue_homography"
    assert result.accepted is True


def test_quad_from_azure_ink_points():
    xs = np.linspace(40, 160, 20)
    ys = np.linspace(50, 200, 25)
    xx, yy = np.meshgrid(xs, ys)
    points = np.stack([xx.ravel(), yy.ravel()], axis=1).astype(np.float32)
    quad = quad_from_azure_ink_points(points, image_size=(200, 260))
    assert quad is not None
    assert quad.reason == "AZURE_DI_PAGE_CORNERS"
    assert 0.15 <= quad.area_ratio <= 0.95


class _FakeAnalyzer:
    def analyze_raw(self, image_bytes: bytes) -> dict:
        assert image_bytes
        words = []
        for x0, y0 in ((40, 50), (150, 50), (150, 200), (40, 200), (90, 120)):
            words.append(
                {
                    "content": "X",
                    "polygon": [
                        x0,
                        y0,
                        x0 + 10,
                        y0,
                        x0 + 10,
                        y0 + 10,
                        x0,
                        y0 + 10,
                    ],
                    "confidence": 0.9,
                }
            )
        return {
            "status": "succeeded",
            "analyzeResult": {
                "content": "X",
                "pages": [
                    {
                        "pageNumber": 1,
                        "width": 200,
                        "height": 260,
                        "unit": "pixel",
                        "words": words,
                    }
                ],
            },
        }


def test_run_azure_di_page_corners_with_injected_analyzer():
    img = Image.new("L", (200, 260), color=245)
    result = run_azure_di_page_corners(img, analyzer=_FakeAnalyzer())
    assert result.attempted is True
    assert result.configured is True
    assert result.quad is not None
    assert result.reason == "AZURE_DI_PAGE_CORNERS_OK"
    result.quad.rectified.close()


def test_escalation_order_quad_lightglue_azure_hitl():
    load_secondary_policy.cache_clear()
    first = plan_field_escalation(
        gap_class="CATASTROPHIC_TRANSFORM", field_name="*"
    )
    assert first.tool == EscalationTool.DOCUMENT_QUAD_RECOVERY

    second = plan_field_escalation(
        gap_class="CATASTROPHIC_TRANSFORM",
        field_name="*",
        document_quad_attempted=True,
    )
    assert second.tool == EscalationTool.LEARNED_MATCHER

    third = plan_field_escalation(
        gap_class="REGISTRATION_FAILED",
        field_name="*",
        document_quad_attempted=True,
        learned_matcher_attempted=True,
    )
    # Full-page Azure DI corners are off by default (low-cost); next is HITL.
    assert third.tool == EscalationTool.OPENCV_REGISTRATION_HITL

    # When policy enables corners, Azure DI is preferred over HITL.
    corners_policy = dict(load_secondary_policy())
    corners_policy["registration_azure_di_corners_enabled"] = True
    third_on = plan_field_escalation(
        gap_class="REGISTRATION_FAILED",
        field_name="*",
        document_quad_attempted=True,
        learned_matcher_attempted=True,
        policy=corners_policy,
    )
    assert third_on.tool == EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ

    fourth = plan_field_escalation(
        gap_class="REGISTRATION_FAILED",
        field_name="*",
        document_quad_attempted=True,
        learned_matcher_attempted=True,
        azure_di_corners_attempted=True,
        policy=corners_policy,
    )
    assert fourth.tool == EscalationTool.OPENCV_REGISTRATION_HITL
