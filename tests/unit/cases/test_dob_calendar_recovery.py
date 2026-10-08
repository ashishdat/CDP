import pytest

from packages.extraction_recovery.field_cascade import semantic_accept


@pytest.mark.parametrize("value", ["02/30/2000", "02/29/2001", "13/01/2000", "00/10/2000", "023001", "13312000"])
def test_impossible_date_cannot_stop_crop_recovery(value):
    assert semantic_accept("patient_dob", value) == (False, "INVALID_CALENDAR_DATE")


@pytest.mark.parametrize("value", ["02/29/2000", "03/23/1949", "01/30/26", "2000-02-29", "013026", "02292000"])
def test_observed_valid_date_remains_usable(value):
    assert semantic_accept("patient_dob", value) == (True, "DATE_SHAPED")
