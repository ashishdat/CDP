from workers.field_candidates.reconciliation import reconcile_candidates


def test_malformed_complete_name_component_does_not_suppress_engine_consensus():
    candidates = [
        {
            "value": "YOLANA",
            "provider": "paddle_original",
            "engine": "paddleocr",
            "validation_results": ["person_name_component"],
        },
        {
            "value": "YOLANA",
            "provider": "tesseract_psm_6",
            "engine": "tesseract",
            "validation_results": ["person_name_component"],
        },
        {
            "value": "5 PATIENT'S ADDRESS (NO.",
            "provider": "expanded_block_parser",
            "engine": "paddleocr",
            "validation_results": ["complete_name_block_component"],
        },
    ]

    decision = reconcile_candidates("patient_first", candidates)

    assert decision.value == "YOLANA"


def test_malformed_complete_address_component_does_not_suppress_regional_value():
    candidates = [
        {
            "value": "61 COLEMAN ROAD",
            "provider": "paddle_original",
            "engine": "paddleocr",
            "validation_results": ["non_empty"],
        },
        {
            "value": "61 COLEMAN ROAD STAEA",
            "provider": "expanded_block_parser",
            "engine": "paddleocr",
            "validation_results": ["complete_address_block_component"],
        },
    ]

    decision = reconcile_candidates("insured_addr1", candidates)

    assert decision.value == "61 COLEMAN ROAD"


def test_form_label_cannot_win_patient_name_component():
    decision = reconcile_candidates("patient_first", [
        {
            "value": "NICHOLAS",
            "provider": "page_token_recovery",
            "engine": "paddleocr",
            "validation_results": ["NEEDS_REVIEW"],
        },
        {
            "value": "STREET)",
            "provider": "expanded_block_parser",
            "engine": "paddleocr",
            "validation_results": ["complete_name_block_component"],
        },
    ])

    assert decision.value == "NICHOLAS"


def test_independent_consensus_beats_raw_fragment():
    result = reconcile_candidates("patient_first", [
        {"value": "KARNO,", "provider": "paddle_original", "validation_results": []},
        {"value": "YOLANA", "provider": "paddle_original", "validation_results": ["person_name_component"]},
        {"value": "YOLANA", "provider": "tesseract_psm_6", "validation_results": ["person_name_component"]},
    ])
    assert result.value == "YOLANA"


def test_relationship_rejects_ocr_label_and_keeps_pixel_code():
    result = reconcile_candidates("rel_code", [
        {"value": "SelfXSpouse", "provider": "paddle", "validation_results": []},
        {"value": "01", "provider": "pixel_mark_detection",
         "validation_results": ["single_mark", "winning_margin"]},
    ])
    assert result.value == "01"


def test_close_values_are_ambiguous():
    result = reconcile_candidates("patient_city", [
        {"value": "MALDEN", "provider": "paddle", "validation_results": []},
        {"value": "MOLDAN", "provider": "tesseract", "validation_results": []},
    ])
    assert result.ambiguous
    assert result.value is None
