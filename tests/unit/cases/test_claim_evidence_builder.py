from packages.claim_evidence import ClaimEvidenceBuilder


def _types(items):
    return {item.evidence_type for item in items}


def test_financial_and_date_relationships_create_e6_evidence():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "total_charge": "30.00",
            "statement_period_from": "2026-01-01",
            "statement_period_to": "2026-01-31",
        },
        service_lines=[
            {"units": "2", "rate": "10", "charges": "20.00"},
            {"units": "1", "rate": "10", "charges": "10.00"},
        ],
    )
    assert {
        "CLAIM_TOTAL_WITHIN_TOLERANCE",
        "CLAIM_TOTAL_CONFIRMED",
        "SERVICE_LINE_RECONCILED",
        "DATE_RELATIONSHIP_CONFIRMED",
    } <= _types(result.evidence_items)
    assert not result.contradictions


def test_financial_mismatch_is_an_explicit_claim_contradiction():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={"total_charge": "100.00"},
        service_lines=[{"charges": "90.00"}],
    )
    assert "CLAIM_TOTAL_CONTRADICTION" in _types(result.contradictions)


def test_member_and_provider_internal_consistency_are_e6_not_e5():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "insured_id_number": ["ABC123", "ABC-123"],
            "provider_npi": ["1234567893", "1234567893"],
        },
    )
    assert {"MEMBER_IDENTITY_CONSISTENT", "PROVIDER_IDENTITY_CONSISTENT"} <= _types(
        result.evidence_items
    )
    assert {item.evidence_class.value for item in result.evidence_items} == {"E6"}
    assert all(not item.authoritative for item in result.evidence_items)


def test_ub04_service_line_coherence_and_failure_are_recorded():
    builder = ClaimEvidenceBuilder.load()
    coherent = builder.build(
        claim_id="claim-1",
        document_family="UB04",
        claim_values={},
        service_lines=[{
            "revenue_code": "0450", "hcpcs_code": "G0463",
            "units": "1", "charges": "25.00",
        }],
    )
    assert "UB04_SERVICE_LINE_COHERENT" in _types(coherent.evidence_items)
    invalid = builder.build(
        claim_id="claim-2",
        document_family="UB04",
        claim_values={},
        service_lines=[{"revenue_code": "45", "units": "0", "charges": "25.00"}],
    )
    assert "UB04_SERVICE_LINE_CONTRADICTION" in _types(invalid.contradictions)


def test_empty_box28_with_observed_line_charges_emits_line_totals_reconciled():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={"total_charge": None},
        service_lines=[
            {"charges": "200.00"},
            {"charges": "150.50"},
        ],
    )
    assert "LINE_TOTALS_RECONCILED" in _types(result.evidence_items)
    assert "CLAIM_TOTAL_WITHIN_TOLERANCE" not in _types(result.evidence_items)
    assert not result.contradictions
    item = next(i for i in result.evidence_items if i.evidence_type == "LINE_TOTALS_RECONCILED")
    assert item.value == "350.50"
    assert "total_charge" in item.metadata.get("supported_fields", [])
    assert item.metadata.get("provenance") == "DERIVED_FROM_OBSERVED_LINE_CHARGES"


def test_deferred_box28_contradictory_payload_does_not_mint_financial_conflict():
    """OCR Box 28 soup (825) deferred vs line Σ 450 must not restore → CONFLICT.

    FG payload fallback previously reintroduced the digits-first shell and
    falsely minted FINANCIAL_CONFLICT_HITL despite clean line totals.
    """
    payload = {
        "ranked_candidate": {
            "ocr_candidate": {
                "value": "825.00",
                "raw_value": "825.00",
                "engine": "paddleocr",
            }
        },
        "candidates": [
            {"value": "825.00", "raw_value": "825.00", "engine": "paddleocr"},
            {"value": "825.00", "raw_value": "825.00", "engine": "rapidocr"},
        ],
    }
    result = ClaimEvidenceBuilder.load().build(
        claim_id="M.001",
        document_family="CMS1500",
        claim_values={
            "total_charge": None,
            "_box28_field_payload": payload,
        },
        service_lines=[
            {"charges": "225.00"},
            {"charges": "225.00"},
        ],
    )
    types = _types(result.evidence_items)
    assert "FINANCIAL_CONFLICT_HITL" not in types
    assert "LINE_TOTALS_RECONCILED" in types
    assert not result.contradictions


def test_deferred_box28_agreeing_payload_can_still_relieve_via_geometry():
    """Junk-digit deferral relief: payload that matches Σ may re-enter FG."""
    payload = {
        "ranked_candidate": {
            "ocr_candidate": {
                "value": "450.00",
                "raw_value": "450.00",
                "engine": "paddleocr",
            }
        },
        "candidates": [
            {"value": "450.00", "raw_value": "450.00", "engine": "paddleocr"},
        ],
    }
    result = ClaimEvidenceBuilder.load().build(
        claim_id="agree",
        document_family="CMS1500",
        claim_values={
            "total_charge": None,
            "_box28_field_payload": payload,
        },
        service_lines=[
            {"charges": "225.00"},
            {"charges": "225.00"},
        ],
    )
    types = _types(result.evidence_items)
    assert "FINANCIAL_CONFLICT_HITL" not in types
    # Either FG confirm or LINE_TOTALS — never conflict against matching Σ.
    assert (
        "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED" in types
        or "LINE_TOTALS_RECONCILED" in types
        or "CLAIM_TOTAL_CONFIRMED" in types
    )


def _identity(**overrides):
    values = {
        "patient_name": "CAMARATO JOSHUA",
        "insured_name": "CAMARATO JOSHUA",
        "patient_dob": "03/15/1980",
        "insured_id_number": "A123456789",
    }
    values.update(overrides)
    return ClaimEvidenceBuilder.load().build(
        claim_id="claim-identity",
        document_family="CMS1500",
        claim_values=values,
    )


def test_multi_attribute_identity_requires_name_dob_and_member_id():
    result = _identity()
    assert "MULTI_ATTRIBUTE_IDENTITY_CONFIRMED" in _types(result.evidence_items)
    item = next(
        row for row in result.evidence_items
        if row.evidence_type == "MULTI_ATTRIBUTE_IDENTITY_CONFIRMED"
    )
    assert item.metadata["supported_fields"] == ["patient_name"]
    assert "CAMARATO" not in (item.value or "")


def test_name_agreement_alone_is_not_multi_attribute_identity():
    result = _identity(patient_dob=None, insured_id_number=None)
    assert "MEMBER_RELATIONSHIP_CONFIRMED" in _types(result.evidence_items)
    assert "MULTI_ATTRIBUTE_IDENTITY_CONFIRMED" not in _types(result.evidence_items)


def test_explicit_nonself_relationship_blocks_multi_attribute_identity():
    result = _identity(relationship="SPOUSE")
    assert "MULTI_ATTRIBUTE_IDENTITY_CONFIRMED" not in _types(result.evidence_items)


def test_short_name_fragment_blocks_multi_attribute_identity():
    result = _identity(patient_name="JO", insured_name="JO")
    assert "MULTI_ATTRIBUTE_IDENTITY_CONFIRMED" not in _types(result.evidence_items)


def test_non_self_box2_name_disagreement_does_not_create_authority():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "patient_name": "HARRINGTON, SOPHIE",
            "insured_name": "HARRINGTON, RACHAEL",
            "rel_code": "CHILD",
        },
    )
    assert "BOX2_INDEPENDENT_NAME_AUTHORITY" not in _types(result.evidence_items)
    assert "BOX2_BOX4_NAME_CONFIRMED" not in _types(result.evidence_items)
    assert "PATIENT_INSURED_RELATIONSHIP_CONFLICT" not in _types(result.contradictions)


def test_self_with_distinct_names_is_box2_independent_not_blocking_conflict():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "patient_name": "RIVERA, LARA A",
            "insured_name": "RIVERA, ANDREW",
            "rel_code": "SELF",
            "patient_dob": "1990-01-15",
            "insured_dob": "1965-04-02",
        },
    )
    assert "BOX2_INDEPENDENT_NAME_AUTHORITY" in _types(result.evidence_items)
    assert "PATIENT_INSURED_RELATIONSHIP_CONFLICT" not in _types(result.contradictions)
    assert "DOB_SINGLE_ROLE_EVIDENCE" not in _types(result.contradictions)
    assert "MEMBER_RELATIONSHIP_CONTRADICTION" not in _types(result.contradictions)
    assert "BOX3_BOX11A_DOB_CONFIRMED" not in _types(result.evidence_items)


def test_missing_relationship_with_box2_box4_disagreement_creates_no_authority():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "patient_name": "HARRINGTON, SOPHIE",
            "insured_name": "HARRINGTON, RACHAEL",
        },
    )
    assert "BOX2_INDEPENDENT_NAME_AUTHORITY" not in _types(result.evidence_items)
    assert "PATIENT_INSURED_RELATIONSHIP_CONFLICT" not in _types(result.contradictions)


def test_spouse_disagreement_does_not_escalate_as_conflict():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "patient_name": "SMITH, JANE",
            "insured_name": "SMITH, JOHN",
            "rel_code": "SPOUSE",
        },
    )
    assert "BOX2_INDEPENDENT_NAME_AUTHORITY" not in _types(result.evidence_items)
    assert "PATIENT_INSURED_RELATIONSHIP_CONFLICT" not in _types(result.contradictions)


def test_confirmed_total_not_overridden_by_conflicting_box28_soup_rival():
    """HJI6.016-class: Box 28 == Σ, but a rival OCR (560) must not mint CONFLICT."""
    payload = {
        "ranked_candidate": {
            "ocr_candidate": {
                "value": "160.00",
                "raw_value": "1. 60 00",
                "engine": "rapidocr",
            }
        },
        "alternatives": [
            {
                "ocr_candidate": {
                    "value": "560.00",
                    "raw_value": "560.00.",
                    "engine": "paddleocr",
                }
            }
        ],
        "candidates": [
            {"value": "160.00", "raw_value": "1. 60 00", "engine": "rapidocr"},
            {"value": "560.00", "raw_value": "560.00.", "engine": "paddleocr"},
        ],
    }
    result = ClaimEvidenceBuilder.load().build(
        claim_id="hji6",
        document_family="CMS1500",
        claim_values={
            "total_charge": "160.00",
            "_box28_field_payload": payload,
        },
        service_lines=[
            {
                "charges": "160.00",
                "line_charge_selection": {
                    "disposition": "SELECTED_LOCAL_CHARGE",
                    "amount": "160.00",
                    "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                },
                "candidates": [
                    {"value": "160.00", "engine": "paddleocr"},
                    {"value": "160.00", "engine": "rapidocr"},
                ],
            }
        ],
    )
    types = _types(result.evidence_items)
    assert "CLAIM_TOTAL_CONFIRMED" in types
    assert "FINANCIAL_CONFLICT_HITL" not in types


def test_partial_line_selection_does_not_mint_financial_conflict():
    """Ambiguous skipped rows → PARTIAL_LINES_SKIPPED, never under-sum CONFLICT."""
    result = ClaimEvidenceBuilder.load().build(
        claim_id="partial",
        document_family="CMS1500",
        claim_values={"total_charge": "1160.40"},
        service_lines=[
            {
                "charges": "640.00",
                "line_charge_selection": {
                    "disposition": "AMBIGUOUS_LINE_CHARGE",
                    "amount": None,
                    "reason": "DOLLARS_TRUNCATION_VS_FULLER_READ",
                },
            },
            {
                "charges": "260.00",
                "line_charge_selection": {
                    "disposition": "AMBIGUOUS_LINE_CHARGE",
                    "amount": None,
                    "reason": "DOLLARS_TRUNCATION_VS_FULLER_READ",
                },
            },
            {
                "charges": "260.00",
                "line_charge_selection": {
                    "disposition": "SELECTED_LOCAL_CHARGE",
                    "amount": "260.00",
                    "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                },
                "candidates": [
                    {"value": "260.00", "engine": "paddleocr"},
                    {"value": "260.00", "engine": "rapidocr"},
                ],
            },
        ],
    )
    types = _types(result.evidence_items)
    assert "FINANCIAL_CONFLICT_HITL" not in types
