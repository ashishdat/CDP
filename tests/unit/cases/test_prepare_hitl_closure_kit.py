from evaluation.prepare_hitl_closure_kit import prepare

POLICY = {
    "critical_identity_fields": ["patient_last"],
    "reference_required_reasons": ["REFERENCE_REQUIRED"],
}


def _row(field: str, *, reason: str, review: bool = True) -> dict:
    return {
        "field_identity": {
            "document_id": "D1", "page_number": 1,
            "document_family": "CMS1500", "service_line_number": None,
            "semantic_field": field,
        },
        "selected_value": "VALUE",
        "normalized_value": "VALUE",
        "review_required": review,
        "provenance": {"reason": reason},
        "validation_results": [],
    }


def test_prepare_never_self_approves_predictions() -> None:
    result = prepare([
        _row("patient_last", reason="REFERENCE_REQUIRED"),
        _row("diagnosis_code", reason="INSUFFICIENT_EVIDENCE"),
        _row("total_charge", reason="SELECTED", review=False),
    ], POLICY)
    assert result["summary"]["automatic_approvals_created"] == 0
    assert result["summary"]["reference_decisions_to_complete"] == 1
    assert result["reference_rows"][0]["decision"] == "PENDING"
    assert result["reference_rows"][0]["reference_value"] == ""
    assert result["route_rows"][0]["status"] == "PROPOSED"
    assert result["summary"]["ground_truth_loaded"] is False
