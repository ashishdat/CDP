from workers.field_candidates.parsers import parse_alternatives


def test_printed_field_parsers_emit_only_valid_constrained_alternatives():
    assert parse_alternatives("provider_npi", "1912445669")
    assert not parse_alternatives("provider_npi", "123")
    assert parse_alternatives("patient_dob", "10281977") == [
        ("10281977", ("valid_calendar_date",))
    ]
    assert not parse_alternatives("patient_dob", "02312020")
    assert parse_alternatives("type_of_bill", "0117")[0][0] == "117"
    assert parse_alternatives("patient_zip", "06119")[0][0] == "06119"
    assert parse_alternatives("total_charge", "$123.40")[0][0] == "123.40"
    assert parse_alternatives("patient_last", "Daniels, Dameon")[0][0] == "DANIELS"
    assert parse_alternatives("patient_first", "Simpson, Christopher") == [
        ("CHRISTOPHER", ("person_name_component",)),
        ("CHRISTOPH", ("person_name_component", "fixed_width_output_projection")),
    ]
