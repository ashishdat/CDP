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
    assert "CLAIM_TOTAL_CONFIRMED" not in _types(result.evidence_items)
    assert not result.contradictions
    item = next(i for i in result.evidence_items if i.evidence_type == "LINE_TOTALS_RECONCILED")
    assert item.value == "350.50"
    assert "total_charge" in item.metadata.get("supported_fields", [])
    assert item.metadata.get("provenance") == "DERIVED_FROM_OBSERVED_LINE_CHARGES"


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


def test_non_self_box2_independent_name_authority():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "patient_name": "HARRINGTON, SOPHIE",
            "insured_name": "HARRINGTON, RACHAEL",
            "rel_code": "CHILD",
        },
    )
    assert "BOX2_INDEPENDENT_NAME_AUTHORITY" in _types(result.evidence_items)
    assert "BOX2_BOX4_NAME_CONFIRMED" not in _types(result.evidence_items)
    assert "PATIENT_INSURED_RELATIONSHIP_CONFLICT" not in _types(result.contradictions)


def test_self_with_distinct_names_is_relationship_conflict_not_forced_equal():
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
    assert "PATIENT_INSURED_RELATIONSHIP_CONFLICT" in _types(result.contradictions)
    assert "DOB_SINGLE_ROLE_EVIDENCE" in _types(result.contradictions)
    assert "BOX3_BOX11A_DOB_CONFIRMED" not in _types(result.evidence_items)
    assert "BOX2_INDEPENDENT_NAME_AUTHORITY" in _types(result.evidence_items)
