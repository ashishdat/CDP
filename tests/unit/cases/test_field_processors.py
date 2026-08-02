"""Field-type normalization: parsing only, not validation (see
workers/standard_form_extraction/field_processors.py docstring)."""

from decimal import Decimal

from workers.standard_form_extraction.field_processors import (
    normalize,
    normalize_checkbox,
    normalize_currency,
    normalize_date,
    normalize_npi,
    normalize_tax_id,
)


def test_normalize_date_accepts_common_formats():
    assert normalize_date("07-16-2025") == ("2025-07-16", True)
    assert normalize_date("07/16/2025") == ("2025-07-16", True)
    assert normalize_date("07162025") == ("2025-07-16", True)
    assert normalize_date("01 30 26") == ("2026-01-30", True)


def test_normalize_date_two_digit_year_pivots_at_50():
    assert normalize_date("07-16-25") == ("2025-07-16", True)
    assert normalize_date("07-16-72") == ("1972-07-16", True)


def test_normalize_date_rejects_garbage():
    value, ok = normalize_date("not a date")
    assert not ok
    assert value is None


def test_normalize_currency_strips_symbols_and_commas():
    assert normalize_currency("$1,675.00") == (Decimal("1675.00"), True)
    assert normalize_currency("175.00") == (Decimal("175.00"), True)
    assert normalize_currency("($80.55)") == (Decimal("-80.55"), True)
    assert normalize_currency("($80.55)|") == (Decimal("-80.55"), True)


def test_normalize_currency_rejects_empty():
    value, ok = normalize_currency("   ")
    assert not ok
    assert value is None


def test_normalize_npi_requires_exactly_ten_digits():
    assert normalize_npi("1396827531") == ("1396827531", True)
    assert normalize_npi("139-682-7531") == ("1396827531", True)
    value, ok = normalize_npi("12345")
    assert not ok
    assert value is None


def test_normalize_tax_id_requires_exactly_nine_digits():
    assert normalize_tax_id("72-1216996") == ("721216996", True)
    _value, ok = normalize_tax_id("123")
    assert not ok


def test_normalize_checkbox_variants():
    assert normalize_checkbox("X") == (True, True)
    assert normalize_checkbox("[X]") == (True, True)
    assert normalize_checkbox("") == (False, True)
    value, ok = normalize_checkbox("maybe")
    assert not ok
    assert value is None


def test_normalize_dispatches_by_field_type():
    value, ok = normalize("currency", "$150.00")
    assert ok
    assert value == "150.00"

    value, ok = normalize("npi", "1396827531")
    assert ok
    assert value == "1396827531"


def test_normalize_unknown_field_type_falls_back_to_text():
    value, ok = normalize("something_unrecognized", "  raw text  ")
    assert ok
    assert value == "raw text"
