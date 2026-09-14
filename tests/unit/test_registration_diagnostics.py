from copy import deepcopy

from workers.page_detection.registration_diagnostics import build_report, write_report


def document(evidence=None):
    return {"template_selection": {"candidate_templates": [
        {"template_id": "cms1500", "page_number": 1, "scores": {"registration": 0.2},
         "diagnostics": {"registration_evidence": evidence}}]}}


def test_old_scores_do_not_invent_failure_or_coordinates(tmp_path):
    source = document()
    before = deepcopy(source)
    report = write_report(source, tmp_path)
    assert source == before
    attempt = report["attempts"][0]
    assert attempt["first_failing_stage"] is None
    assert attempt["first_failing_stage_status"] == "UNAVAILABLE"
    assert attempt["feature_matching"]["matched_features"] is None
    assert "Feature coordinates were not recorded" in (tmp_path / "registration_report.html").read_text()


def test_first_known_failure_follows_stage_order():
    report = build_report(document({"accepted": False,
        "rejection_reason": "invalid_transformed_corners,insufficient_inliers"}))
    assert report["attempts"][0]["first_failing_stage"] == "Homography"


def test_cheap_failure_and_final_attempt_are_separate():
    source = document({"accepted": True, "transform_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]})
    diagnostic = source["template_selection"]["candidate_templates"][0]["diagnostics"]
    diagnostic["cheap_registration_evidence"] = {
        "algorithm": "edge_phase_correlation", "alignment_confidence": 0.5,
        "accepted": False, "rejection_reason": "cheap_confidence_below_threshold"}
    diagnostic["registration_policy"] = {"cheap_min_confidence": 0.92}
    report = build_report(source)
    assert report["attempt_count"] == 2
    assert report["attempts"][0]["first_failing_stage"] == "Acceptance"
    assert report["attempts"][0]["acceptance"]["delta_to_threshold"] < 0
    assert report["attempts"][1]["first_failing_stage_status"] == "NOT_APPLICABLE"


def test_no_evidence_is_not_a_registration_attempt():
    assert build_report({"registration": {"status": "UNAVAILABLE"}})["attempt_count"] == 0
