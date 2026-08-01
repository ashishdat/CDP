from packages.local_candidate_repairs import clean_city_candidate, repair_handwritten_address


def test_city_cleanup_preserves_visible_letters_only() -> None:
    assert clean_city_candidate("# Scottsdale .") == "SCOTTSDALE"
    assert clean_city_candidate("CITY") is None


def test_address_repair_is_narrow_and_requires_street_evidence() -> None:
    assert repair_handwritten_address("25( Salem Street . 1 .") == "252 SALEM STREET"
    assert repair_handwritten_address("25(") is None
    assert repair_handwritten_address("( Salem Street") is None
