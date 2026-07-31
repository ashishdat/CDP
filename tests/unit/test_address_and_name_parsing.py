from workers.field_candidates.address_block import parse_address_block, reconstruct_lines
from workers.field_candidates.name_interpretations import interpret_complete_name
from workers.field_candidates.reconciliation import reconcile_candidates


def test_address_token_order_is_geometry_not_confidence():
    tokens = [
        {"text": "ST", "x0": 100, "y0": 10, "x1": 120, "y1": 30, "confidence": .99},
        {"text": "123", "x0": 10, "y0": 10, "x1": 40, "y1": 30, "confidence": .1},
        {"text": "MAIN", "x0": 50, "y0": 10, "x1": 90, "y1": 30, "confidence": .5},
    ]
    assert reconstruct_lines(tokens) == ["123 MAIN ST"]


def test_complete_address_block_parses_components():
    result = parse_address_block(["123 MAIN ST", "APT 4", "AUSTIN, TX 78731"])
    assert (result.addr1, result.addr2, result.city, result.state, result.zip_code) == (
        "123 MAIN ST", "APT 4", "AUSTIN", "TX", "78731"
    )


def test_complete_name_generates_both_conventions():
    values = interpret_complete_name("RUMMEL, SHELIA F")
    assert any(item.last == "RUMMEL" and item.first == "SHELIA" for item in values)


def test_routing_only_token_cannot_populate_name():
    result = reconcile_candidates("patient_first", [
        {"value": "AMOUNT PAID", "provider": "page", "validation_results": [],
         "evidence_role": "ROUTING_ONLY"}
    ])
    assert result.value is None


def test_valid_regional_handwriting_beats_high_confidence_label():
    result = reconcile_candidates("patient_first", [
        {"value": "PATIENT NAME", "provider": "page", "validation_results": [],
         "evidence_role": "ROUTING_ONLY", "confidence": .99},
        {"value": "SHELIA", "provider": "handwriting", "validation_results": ["person_name_component"],
         "confidence": .55},
    ])
    assert result.value == "SHELIA"


def test_empty_regional_candidate_cannot_inherit_routing_confidence():
    result = reconcile_candidates("patient_first", [
        {"value": "", "provider": "regional", "validation_results": [], "confidence": .99},
        {"value": "PROCEDURE CODE", "provider": "page", "validation_results": [],
         "evidence_role": "ROUTING_ONLY", "confidence": .99},
    ])
    assert result.value is None
