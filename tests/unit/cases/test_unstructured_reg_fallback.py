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


def test_mailroom_separator_yields_no_fields():
    text = """
*00BREAK00*
Document Separator
Used to Separate Each Transaction
SourceHOV, Inc 4050 South 500 West Salt Lake City, UT 84123
Patch II
08/13/2026 0500
"""
    assert _heuristic_fields_from_di_text(text) == {}


def test_mailroom_unique_id_cover_yields_no_fields():
    text = """
DOCSEP
Unique ID
CERT161008
Tracking No
420841300755950011584431622266.
Last Name
First Name
RecvDate
08/18/2026
Arrival Date
08/18/2026
POBox
30755
"""
    assert _heuristic_fields_from_di_text(text) == {}


def test_ub04_prefers_person_over_facility_name():
    text = """
UB-04 CMS-1450
TYPE OF BILL 0212
KAISER FOUNDATION HOS SAC 2025 MORSE AVE
8 PATIENT NAME
9 PATIENT ADDRESS a
b HALL, SHELLETHA R.
10 BIRTHDATE
11051962
47 TOTAL CHARGES
2079.00
60 INSURED'S UNIQUE ID
958252115
58 INSURED'S NAME
HALL, SHELLETHA R.
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "HALL" in name and "SHELLETHA" in name
    assert "KAISER" not in name
    assert fields.get("patient_dob") == "11/05/1962"
    assert fields.get("insured_id_number") == "958252115"
    assert "2079.00" in (fields.get("total_charge") or "")


def test_city_state_not_treated_as_person_name():
    text = """
UB-04 CMS-1450
HEMPSTEAD, NY 11550
LOPEZRODRIGUEZ, MAYULEISI
10 BIRTHDATE
08061991
112592214
253.00
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "LOPEZRODRIGUEZ" in name
    assert "HEMPSTEAD" not in name


def test_fax_boilerplate_not_treated_as_person_name():
    text = """
FAX IMAGE - ORIGINAL SOURCE MAY BE BAD, THEREFORE BETTER IMAGE QUALITY CANNOT BE OBTAINED
08/18/2026
"""
    assert _heuristic_fields_from_di_text(text) == {}
