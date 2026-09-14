from copy import deepcopy

from workers.page_detection.registration_diagnostics import build_report, write_report


def document(events):
    return {"registration_trace": {"traces": [{"trace_id": "test", "events": events,
                                               "missing_events": []}]}}


def event(stage, status, **data):
    return {"stage": stage, "status": status, "data": data, "reason": "recorded reason"}


def test_old_scores_do_not_invent_history(tmp_path):
    source = {"template_selection": {"candidate_templates": [
        {"template_id": "cms1500", "scores": {"registration": 0.2}}]}}
    before = deepcopy(source)
    report = write_report(source, tmp_path)
    assert source == before
    assert report["attempt_count"] == 0
    assert (tmp_path / "registration_report.html").is_file()


def test_first_failure_is_emitted_order_not_inferred_order():
    report = build_report(document([event("Transform", "FAILED"),
                                    event("Homography", "FAILED"),
                                    event("Registration Finished", "FAILED")]))
    assert report["attempts"][0]["first_failing_stage"] == "Transform"


def test_later_acceptance_does_not_reuse_cheap_threshold():
    source = document([event("Acceptance", "STARTED", threshold=0.92),
                       event("Acceptance", "FAILED"), event("Acceptance", "STARTED"),
                       event("Registration Finished", "SUCCESS",
                             evidence={"accepted": True, "alignment_confidence": 0.7})])
    report = build_report(source)
    assert report["attempts"][0]["acceptance"]["threshold"] is None
    assert report["attempts"][0]["acceptance"]["score"] == 0.7


def test_no_evidence_is_not_a_registration_attempt():
    assert build_report({"registration": {"status": "UNAVAILABLE"}})["attempt_count"] == 0
