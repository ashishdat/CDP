"""Unit tests for unstructured REG fallback heuristics + DOB YY MM DD."""

from __future__ import annotations

from packages.extraction_recovery.span_selection import _assemble_dob_from_tokens
from packages.extraction_recovery.unstructured_reg_fallback import (
    _heuristic_fields_from_di_text,
)


def test_dob_yy_mm_dd_after_header_strip():
    assert _assemble_dob_from_tokens("YY 74 MM 03/12") == "03/12/1974"
    assert _assemble_dob_from_tokens("74 03 12") == "03/12/1974"


def test_dob_mim_header_garble_stripped():
    assert _assemble_dob_from_tokens("MIM 12 30 200") == "12/30/2020"


def test_unstructured_heuristic_prefers_historical_dob_and_digit_id():
    text = """
Maines, Tammy L
01 08 69
United Healthcare
959012644
150.00
08/17/2026
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "01/08/1969"
    assert fields.get("insured_id_number") == "959012644"
    assert "MAINES" in (fields.get("patient_name") or "").upper()
    assert "150.00" in (fields.get("total_charge") or "")


def test_unstructured_heuristic_inline_dob_in_mixed_line():
    """HJHO.014-class: DOB tokens sit inside a freeform identity line."""
    text = """
M . Maines, Tammy L 1040 Lenox Valley Dv NE Atlanta 30324 01 08 69 United Healthcare
959012644
120.00
08/17/2026 0500
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "01/08/1969"
    assert fields.get("insured_id_number") == "959012644"
    assert "120.00" in (fields.get("total_charge") or "")


def test_unstructured_heuristic_skips_po_box_as_name():
    text = """
P. O. BOX 30755 SALTLAKECITY, UT 84130-0755 959298836
150.00
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "P. O. BOX" not in name and "SALT LAKE" not in name
