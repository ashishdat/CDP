from packages.evaluation.family_metrics import family_metrics
from packages.recovery.independent_failures import failure_category


def test_proposal_attempts_do_not_turn_template_selection_into_alignment_failure():
    assert failure_category({"disposition": "REGISTRATION_FAILED", "registration_ok": False,
        "registration_reason": "NO_TEMPLATE_ABOVE_THRESHOLD",
        "registration_attempt_count": 5}) == "TEMPLATE_SELECTION_FAILURE"
    assert failure_category({"disposition": "REGISTRATION_FAILED", "registration_ok": False,
        "registration_reason": "insufficient_inliers",
        "registration_attempt_count": 1}) == "ALIGNMENT_FAILURE"


def test_verified_scoring_does_not_hide_identifier_separator_loss():
    row = {"document": "case", "source_sha256": "source", "finished": True,
           "completed": True, "true_stp": False, "fields": {
               "insured_id_number": {"disp": "AUTO_ACCEPTED", "value": "OSC7512674401"}}}
    truth = {"claims": {"case": {"source_sha256": "source", "fields": {
        "insured_id_number": {"value": "OSC75126744-01",
                              "verification_status": "OPERATOR_SUPPLIED_VERIFIED"}}}}}
    report = family_metrics([row], truth=truth)["overall"]
    assert report["verified_accepted_fields_scored"] == 1
    assert report["verified_false_accepts"] == 1
    row["fields"]["insured_id_number"]["value"] = "OSC75126744-01"
    assert family_metrics([row], truth=truth)["overall"]["verified_false_accepts"] == 0
