"""ID_SHAPED requires digit mass so letter soup cannot outrank pad+digit ink."""

from packages.extraction_recovery.field_cascade import pick_engine_candidates, semantic_accept


def test_letter_soup_is_not_id_shaped():
    ok, reason = semantic_accept("insured_id_number", "eee ae | ONNNAAIVKRT")
    assert ok is False
    assert reason == "NOT_ID_SHAPED"


def test_zero_padded_digit_id_is_shaped_for_cascade_ranking():
    ok, reason = semantic_accept("insured_id_number", "0000007267")
    assert ok is True
    assert reason == "ID_SHAPED"


def test_pick_prefers_multi_engine_digits_over_tesseract_soup():
    selected, _raw, reason, _ordered = pick_engine_candidates(
        "insured_id_number",
        [
            {"value": "0000007267", "engine": "paddleocr"},
            {"value": "0000007267", "engine": "rapidocr"},
            {"value": "eee ae | ONNNAAIVKRT", "engine": "tesseract"},
        ],
        "ALPHANUMERIC_ID",
    )
    assert selected == "0000007267"
    assert reason.startswith("MULTI_ENGINE_AGREEMENT")
