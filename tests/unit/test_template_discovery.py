from copy import deepcopy

from workers.page_detection.template_discovery import build_report, write_report


def document(scores, **diagnostics):
    return {"template_selection": {"template_id": None, "reason": "NO_TEMPLATE_ABOVE_THRESHOLD",
            "candidate_templates": [{"template_id": "cms1500", "template_version": "02-12",
                                     "page_number": 1, "scores": scores,
                                     "diagnostics": diagnostics, "reasons": []}]}}


def test_historical_registration_failure_preserves_missing_evidence(tmp_path):
    source = document({"anchors": 0.0, "features": 0.6, "registration": 0.2})
    before = deepcopy(source)
    report = write_report(source, tmp_path)
    assert source == before
    assert report["status"] == "REGISTRATION_FAILURE"
    row = report["candidate_templates"][0]
    assert row["matched_features"] is None
    assert row["homography_score"] is None
    assert row["delta_to_threshold"]["registration"] < 0
    assert (tmp_path / "template_discovery.json").is_file()
    assert (tmp_path / "template_discovery.html").is_file()


def test_no_anchor_attempt_is_discovery_failure():
    assert build_report(document({}))["status"] == "DISCOVERY_FAILURE"
    # An attempted zero-score anchor match is not an unattempted stage.
    assert build_report(document({"anchors": 0}))["status"] != "DISCOVERY_FAILURE"


def test_near_threshold_requires_consistency_and_no_competitor():
    source = document({"anchors": 0, "features": 0.73})
    assert build_report(source)["status"] != "THRESHOLD_CANDIDATE"
    rows = source["template_selection"]["candidate_templates"]
    rows.append({**deepcopy(rows[0]), "page_number": 2})
    assert build_report(source)["status"] == "THRESHOLD_CANDIDATE"
    rows.append({**deepcopy(rows[0]), "template_id": "ub04"})
    assert build_report(source)["status"] != "THRESHOLD_CANDIDATE"


def test_ambiguity_never_promotes_a_winner():
    source = document({"anchors": 1.0})
    source["template_selection"]["reason"] = "AMBIGUOUS_TEMPLATE"
    report = build_report(source)
    assert report["status"] == "AMBIGUOUS_TEMPLATE"
    assert not report["candidate_templates"][0]["selected"]


def test_html_escapes_recorded_strings(tmp_path):
    source = document({"anchors": 0})
    source["template_selection"]["candidate_templates"][0]["reasons"] = ["<script>alert(1)</script>"]
    write_report(source, tmp_path)
    html = (tmp_path / "template_discovery.html").read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
