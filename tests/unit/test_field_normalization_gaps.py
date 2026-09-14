"""Unit checks for date ISO acceptance and ICD OCR letter repair."""

from packages.field_normalization import normalize_date, normalize_icd
from packages.local_evidence_cascade import decide_local_candidate


def test_normalize_date_accepts_iso_and_us_forms():
    assert normalize_date("1965-12-09") == ("1965-12-09", True)
    assert normalize_date("12/09/1965") == ("1965-12-09", True)
    assert normalize_date("1 2 /0 9 /1 9 6 5") == ("1965-12-09", True)


def test_decide_local_candidate_dates_agree_across_formats():
    iso = decide_local_candidate("1965-12-09", "DATE")
    us = decide_local_candidate("12/09/1965", "DATE")
    assert iso.accepted and us.accepted
    assert iso.normalized_value == us.normalized_value == "1965-12-09"


def test_normalize_icd_repairs_leading_i_as_one():
    assert normalize_icd("110") == ("I10", True)
    assert normalize_icd("I10") == ("I10", True)
    decision = decide_local_candidate("110", "ICD_CODE")
    assert decision.accepted
    assert decision.normalized_value == "I10"
