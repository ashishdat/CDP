from packages.deterministic_field_tuning import eligible_for_consensus_acceptance, validate_field


def test_npi_requires_checksum_and_consensus():
    row = {
        "field_identity": {"semantic_field": "rendering_provider_npi"},
        "selected_value": "a\n1396827531",
        "validation_results": ["CROSS_FAMILY_AGREEMENT"],
    }
    result = eligible_for_consensus_acceptance(row)
    assert result.valid
    assert result.normalized_value == "1396827531"


def test_valid_format_without_consensus_is_not_eligible():
    row = {
        "field_identity": {"semantic_field": "procedure_code"},
        "selected_value": "96133",
        "validation_results": [],
    }
    assert not eligible_for_consensus_acceptance(row).valid


def test_diagnosis_trailing_period_is_normalized():
    result = validate_field("principal_diagnosis", "F33.3.")
    assert result.valid
    assert result.normalized_value == "F33.3"


def test_controlled_codes_require_exact_valid_values():
    assert validate_field("type_of_bill", "117").valid
    assert validate_field("patient_sex", "F").valid
    assert validate_field("rel_code", "SELF").valid
    assert not validate_field("rel_code", "Sell").valid
    assert validate_field("diagnosis_pointer", "A B").valid


def test_blank_requires_independent_blank_agreement():
    row = {
        "field_identity": {"semantic_field": "patient_paid"},
        "selected_value": None,
        "validation_results": ["SEMANTIC_BLANK_EVIDENCE"],
    }
    assert not eligible_for_consensus_acceptance(row).valid
    row["validation_results"].append("CROSS_ENGINE_BLANK_AGREEMENT")
    assert eligible_for_consensus_acceptance(row).valid
