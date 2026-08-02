from workers.table_extraction.normalization import normalize_cell


def test_blank_is_preserved_without_neighbor_inference():
    assert normalize_cell("", "revenue_code") == (
        "", "PRESERVE_BLANK", "VALID_BLANK", False
    )


def test_code_normalization_does_not_fabricate_characters():
    value, transformation, valid, acceptable = normalize_cell(" 0450 ", "revenue_code")
    assert value == "0450"
    assert transformation == "CODE_CASE_SPACE"
    assert valid == "VALID"
    assert acceptable


def test_invalid_date_is_not_repaired():
    value, _, valid, acceptable = normalize_cell("02/31/2026", "service_date")
    assert value == "02/31/2026"
    assert valid == "INVALID"
    assert not acceptable


def test_structured_normalization_handles_common_claim_formats():
    assert normalize_cell("01 30 26", "service_date")[:3] == (
        "2026-01-30", "VALID_DATE_ISO", "VALID"
    )
    assert normalize_cell("($80.55)", "adjustment")[:3] == (
        "-80.55", "CURRENCY_EVIDENCE", "VALID"
    )
    assert normalize_cell("($80.55)|", "adjustment")[:3] == (
        "-80.55", "CURRENCY_EVIDENCE", "VALID"
    )
    assert normalize_cell("F33.3.", "principal_diagnosis")[:3] == (
        "F33.3", "CODE_CASE_SPACE", "VALID"
    )
