import json

import pytest
from PIL import Image

from workers.page_detection.registration_diagnostics import build_report
from workers.page_detection.registration_telemetry import (
    FIELDS,
    RegistrationTrace,
    collect_traces,
    save_traces,
)
from workers.page_detection.template_alignment import align_to_reference


def test_live_events_order_serialization_failures_and_missing_stages(tmp_path):
    with collect_traces() as traces, Image.new("L", (100, 100), 255) as image:
        result = align_to_reference(image, image)
    assert not result.accepted
    assert len(traces) == 1
    events = traces[0].events
    assert events[0]["stage"] == "Registration Started"
    assert events[-1]["stage"] == "Registration Finished"
    assert events[-1]["status"] == "FAILED"
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert any(event["status"] == "FAILED" and event["reason"] for event in events)
    assert all(set(FIELDS) <= event.keys() for event in events)
    assert all(event["latency"] >= 0 for event in events)
    assert events[1]["status"] == "SKIPPED"
    payload = save_traces(traces, tmp_path)
    assert json.loads((tmp_path / "registration_trace.json").read_text()) == payload
    assert "Homography" in payload["traces"][0]["missing_events"]
    report = build_report({"registration_trace": payload})
    assert report["attempt_count"] == 1
    assert report["attempts"][0]["first_failing_stage"] == "Feature Matching"


def test_latency_uses_monotonic_clock():
    values = iter((1.0, 2.0, 2.125))
    trace = RegistrationTrace(clock=lambda: next(values))
    trace.start("Feature Matching")
    trace.end("FAILED", "insufficient_keypoints")
    assert trace.events[-1]["latency"] == 125.0


def test_exception_emits_finish_and_preserves_exception():
    with collect_traces() as traces, pytest.raises(AttributeError):
        align_to_reference(None, None)
    assert traces[0].events[-1]["reason"] == "AttributeError"
    assert traces[0].events[-1]["status"] == "FAILED"


def test_reports_do_not_reconstruct_old_registration_scores():
    report = build_report({"template_selection": {"candidate_templates": [
        {"template_id": "cms1500", "scores": {"registration": 0.2}}]}})
    assert report["attempt_count"] == 0


def test_collection_is_scoped_and_does_not_leak():
    with collect_traces() as outer, Image.new("L", (50, 50), 255) as image:
        with collect_traces() as inner:
            align_to_reference(image, image)
        assert not outer
        assert len(inner) == 1
        align_to_reference(image, image)
    assert len(outer) == 1


def test_instrumentation_preserves_real_registration_result():
    import numpy as np
    from PIL import ImageDraw

    with Image.new("L", (300, 400), 255) as image:
        draw = ImageDraw.Draw(image)
        for y in range(30, 370, 30):
            draw.line((20, y, 280, y), fill=0, width=2)
        for x in range(20, 281, 40):
            draw.line((x, 30, x, 360), fill=0, width=2)
        plain = align_to_reference.__wrapped__(image, image)
        with collect_traces() as traces:
            traced = align_to_reference(image, image)
        assert traced.accepted == plain.accepted
        assert traced.method == plain.method
        assert traced.alignment_score == plain.alignment_score
        if traced.homography is not None:
            np.testing.assert_array_equal(traced.homography, plain.homography)
        assert traces[0].events[-1]["status"] == ("SUCCESS" if traced.accepted else "FAILED")
        for result in (plain, traced):
            if result.warped is not None:
                result.warped.close()


def test_event_is_emitted_before_feature_engine_executes(monkeypatch):
    from workers.page_detection import template_alignment
    from workers.page_detection.registration_telemetry import ACTIVE

    def fail_at_feature_engine(**kwargs):
        assert ACTIVE.get().events[-1]["stage"] == "Feature Matching"
        assert ACTIVE.get().events[-1]["status"] == "STARTED"
        raise RuntimeError("engine failure")

    monkeypatch.setattr(template_alignment.cv2, "SIFT_create", fail_at_feature_engine)
    with (Image.new("L", (100, 100), 255) as image, collect_traces() as traces,
          pytest.raises(RuntimeError, match="engine failure")):
        align_to_reference(image, image)
    assert traces[0].events[-2]["stage"] == "Feature Matching"
    assert traces[0].events[-2]["status"] == "FAILED"
