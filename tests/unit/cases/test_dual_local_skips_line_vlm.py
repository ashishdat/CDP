"""Dual-local charge agreement must skip Claude/gpt-4o line crops."""

from scripts.ocr_from_geometry import _dual_local_engines_agree_on_charge


def test_dual_local_agree_skips_vlm_gate():
    assert _dual_local_engines_agree_on_charge(
        "640.00",
        [
            {"engine": "paddleocr", "value": "640.00"},
            {"engine": "rapidocr", "value": "640.00"},
        ],
    )


def test_single_local_does_not_skip():
    assert not _dual_local_engines_agree_on_charge(
        "640.00",
        [{"engine": "paddleocr", "value": "640.00"}],
    )


def test_cents_twin_still_counts_as_dual_local():
    assert _dual_local_engines_agree_on_charge(
        "640.00",
        [
            {"engine": "paddleocr", "value": "640.00"},
            {"engine": "rapidocr", "value": "640.40"},
        ],
    )
