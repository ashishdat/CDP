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
