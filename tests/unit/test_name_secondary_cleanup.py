"""Name recovery cleanup for STP/HITL: drop single-glyph OCR debris."""

from workers.standard_form_extraction.extractor import (
    _clean_secondary_name,
    _reconcile_secondary_name,
)
from packages.local_evidence_cascade import decide_local_candidate


def test_clean_secondary_name_drops_isolated_letter_debris():
    assert _clean_secondary_name("PRIYA E BROWN I MD") == "PRIYA BROWN MD"
    assert _clean_secondary_name("PRIYABROWNMD") == "PRIYA BROWN MD"


def test_clean_secondary_name_peels_glued_org_suffix():
    assert _clean_secondary_name("RIVERVALLEYHOSPITAL", split_md=False) == "RIVERVALLEY HOSPITAL"
    assert _clean_secondary_name("SUNRISEHEALTH SYSTEM", split_md=False) == "SUNRISE HEALTH SYSTEM"
    assert _clean_secondary_name("SUNRISEHEALTHSYSTEM", split_md=False) == "SUNRISE HEALTH SYSTEM"
    assert _clean_secondary_name("ROBERTGARCIAMD") == "ROBERT GARCIA MD"
    assert _clean_secondary_name("ROBERT-JOHNSON") == "ROBERT JOHNSON"
    assert _clean_secondary_name("FACIEPTTYT NORTHSIDE MEDICAL CENTER") == "NORTHSIDE MEDICAL CENTER"


def test_regional_name_recovery_beats_glued_primary():
    primary = "PRIYABROWNMD"
    regional = _clean_secondary_name("PRIYA E BROWN I MD")
    recovered = _reconcile_secondary_name(primary, regional)
    assert recovered == "PRIYA BROWN MD"
    decision = decide_local_candidate(recovered, "PERSON_OR_ORGANIZATION")
    assert decision.accepted is True
    assert decision.normalized_value == "PRIYA BROWN MD"


def test_reconcile_drops_one_surplus_letter_inside_token():
    primary = "PRIYABROWNMD"
    regional = "PRIYA BROWNI MD"
    assert _reconcile_secondary_name(primary, regional) == "PRIYA BROWN MD"

