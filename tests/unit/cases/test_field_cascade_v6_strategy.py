"""Unit tests for field-cascade-v6 strategy loading and crop ladder ordering."""

from __future__ import annotations

from packages.extraction_recovery.field_cascade import FieldCascade, crop_variants
from packages.extraction_recovery.gap_taxonomy import classify_field_gap
from packages.extraction_recovery.strategy import (
    crop_ladder_for,
    load_cascade_strategy,
    post_miss_for,
)


def test_strategy_is_v6():
    strategy = load_cascade_strategy()
    assert strategy.strategy_id == "field-cascade-v6"
    assert strategy.status == "ACTIVE"


def test_dob_ladder_includes_year_wide_and_post_miss_cells():
    assert crop_ladder_for("patient_dob") == (
        "primary",
        "dob_digit_band",
        "dob_loose",
        "dob_year_wide",
    )
    assert "dob_cells" in post_miss_for("patient_dob")


def test_crop_variants_follow_strategy_order():
    variants = crop_variants(
        "patient_dob",
        (672, 424, 871, 457),
        {"x0": 667, "y0": 402, "x1": 886, "y1": 459},
        (1700, 2200),
    )
    ids = [v.variant_id for v in variants]
    assert ids[0] == "primary"
    assert "dob_digit_band" in ids
    assert "dob_year_wide" in ids
    ladder = list(crop_ladder_for("patient_dob"))
    present = [vid for vid in ladder if vid in ids]
    assert ids == present


def test_field_cascade_defaults_to_v6():
    assert FieldCascade().strategy_id == "field-cascade-v6"


def test_gap_taxonomy_marks_header_only_dob_as_handwriting():
    gap = classify_field_gap(
        "patient_dob",
        observed_text="Mly DD",
        accepted=False,
    )
    assert gap is not None
    assert gap.gap_class == "HANDWRITING_UNREADABLE"
