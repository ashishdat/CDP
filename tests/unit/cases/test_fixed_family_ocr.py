from evaluation.run_fixed_family_ocr import (
    _normalize_numeric_ocr,
    _region_key,
    _score,
)


def test_family_title_scoring_tolerates_ocr_noise():
    assert _score("BILLBOFATORY BILL QUEST", ["laboratory bill", "quest diagnostics"]) > 0.3


def test_numeric_ocr_repairs_are_context_limited():
    assert _normalize_numeric_ocr("B4130-0/57") == "84130-0757"


def test_region_cache_key_changes_with_crop_coordinates():
    assert _region_key([0.1, 0.2, 0.3, 0.4]) != _region_key(
        [0.1, 0.21, 0.3, 0.4]
    )
