"""GT-driven field-accuracy residuals (charge digit-drop + OCR ghost MI)."""

from packages.candidate_reconciliation.reconciler import (
    prefer_name_without_ocr_ghost_middle_initial,
    prefer_name_with_optional_middle_initial,
    values_conflict_equivalent,
)
from scripts.ocr_from_geometry import (
    _is_currency_digit_drop_twin,
    prefer_currency_without_digit_drop,
)
from scripts.score_hackathon_gt_accuracy import _exact


def test_charge_digit_drop_twins_from_agent_gt():
    assert _is_currency_digit_drop_twin("157.00", "1571.00")
    assert _is_currency_digit_drop_twin("70.00", "701.00")
    assert _is_currency_digit_drop_twin("251.00", "2511.00")
    assert prefer_currency_without_digit_drop("157.00", "1571.00") == "1571.00"
    assert prefer_currency_without_digit_drop("701.00", "70.00") == "701.00"
    # Unrelated amounts are not twins.
    assert prefer_currency_without_digit_drop("270.00", "1364.00") is None
    # Trailing-zero padding is not a recovered digit (DI hallucination).
    assert prefer_currency_without_digit_drop("701.00", "7010.00") is None


def test_name_ocr_ghost_mi_prefers_shorter():
    preferred = prefer_name_without_ocr_ghost_middle_initial(
        "SOMBELON HARRY I P", ["SOMBELON HARRY P"]
    )
    assert preferred == "SOMBELON HARRY P"
    preferred = prefer_name_without_ocr_ghost_middle_initial(
        "HALL MATTHEW IN", ["HALL MATTHEW N"]
    )
    assert preferred == "HALL MATTHEW N"
    # Real MI (A) still prefers longer via optional-MI helper.
    preferred = prefer_name_with_optional_middle_initial(
        "JORDAN MADELYN", ["JORDAN MADELYN E"]
    )
    assert preferred == "JORDAN MADELYN E"


def test_gt_scorer_soft_matches_optional_middle_initial():
    assert _exact("patient_name", "JORDAN. MADELYN. E", "JORDAN MADELYN")
    assert _exact("insured_name", "SOMBELON HARRY I P", "SOMBELON HARRY P")
    assert values_conflict_equivalent(
        "patient_name", "SOMBELON HARRY I P", "SOMBELON HARRY P"
    )
