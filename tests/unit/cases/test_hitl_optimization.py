from evaluation.optimize_hitl import _load_optional
from packages.hitl_optimization import HitlDisposition, decide, identity_key

POLICY = {
    "reference_required_reasons": ["REFERENCE_REQUIRED"],
    "critical_identity_fields": ["patient_last"],
    "reference_promotion": {
        "required_decision": "REFERENCE_VERIFIED",
        "reject_decisions": ["REFERENCE_CONTRADICTION"],
    },
    "route_promotion": {
        "required_validation_results": ["CROSS_FAMILY_AGREEMENT"],
        "forbidden_validation_results": ["INSUFFICIENT_EVIDENCE"],
    },
}


def _prediction(field: str, *, reason: str | None = None) -> dict:
    return {
        "field_identity": {
            "document_id": "A-01", "page_number": 1, "document_family": "CMS1500",
            "service_line_number": 1, "semantic_field": field,
        },
        "review_required": True,
        "validation_results": ["CROSS_FAMILY_AGREEMENT"],
        "provenance": {"reason": reason},
    }


def test_reference_blocked_field_promotes_only_with_verified_decision() -> None:
    prediction = _prediction("patient_last", reason="REFERENCE_REQUIRED")
    blocked = decide(prediction, POLICY, reference_decisions={}, active_routes=set())
    assert blocked.disposition == HitlDisposition.BLOCKED_REFERENCE_REQUIRED
    verified = decide(
        prediction,
        POLICY,
        reference_decisions={identity_key(prediction): "REFERENCE_VERIFIED"},
        active_routes=set(),
    )
    assert verified.disposition == HitlDisposition.PROMOTED_REFERENCE_VERIFIED


def test_route_requires_active_holdout_promotion() -> None:
    prediction = _prediction("charges")
    route = "CMS1500|charges"
    blocked = decide(prediction, POLICY, reference_decisions={}, active_routes=set())
    assert blocked.disposition == HitlDisposition.BLOCKED_HOLDOUT_REQUIRED
    promoted = decide(prediction, POLICY, reference_decisions={}, active_routes={route})
    assert promoted.disposition == HitlDisposition.PROMOTED_ACTIVE_ROUTE


def test_active_route_still_fails_closed_without_validation() -> None:
    prediction = _prediction("charges")
    prediction["validation_results"] = []
    result = decide(
        prediction,
        POLICY,
        reference_decisions={},
        active_routes={"CMS1500|charges"},
    )
    assert result.disposition == HitlDisposition.BLOCKED_INSUFFICIENT_EVIDENCE


def test_editable_csv_and_yaml_inputs_are_supported(tmp_path) -> None:
    references = tmp_path / "references.csv"
    references.write_text(
        "identity_key,decision\nD1|1|CMS1500||patient_last,REFERENCE_VERIFIED\n",
        encoding="utf-8",
    )
    routes = tmp_path / "routes.yaml"
    routes.write_text(
        "- route_key: CMS1500|diagnosis_code\n  status: ACTIVE\n",
        encoding="utf-8",
    )
    assert _load_optional(references, [])[0]["decision"] == "REFERENCE_VERIFIED"
    assert _load_optional(routes, [])[0]["status"] == "ACTIVE"
