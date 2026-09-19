"""Regression tests for Box 28 geometry and quality lanes."""

from __future__ import annotations

from packages.geometry_authority.box28 import (
    CMS1500_BOX28_FULL,
    box28_value_only_bbox,
    is_box28_field,
)
from packages.geometry_authority.cms1500_regions import CMS1500_BOX28
from packages.geometry_authority.quality_lanes import (
    FormQualityLane,
    classify_cms1500_quality_lane,
)


def test_box28_constant_matches_measured_total_charge_cell():
    assert CMS1500_BOX28 == (1045.0, 1805.0, 1248.0, 1875.0)
    assert CMS1500_BOX28_FULL == (1045, 1805, 1248, 1875)


def test_box28_value_only_excludes_caption_strip():
    x0, y0, x1, y1 = box28_value_only_bbox()
    assert (x0, x1) == (1045, 1248)
    assert y0 == 1805 + 20
    assert y1 == 1875
    assert y0 > 1820  # value band under "28. TOTAL CHARGE"


def test_box28_value_only_does_not_overlap_box29():
    _x0, _y0, x1, _y1 = box28_value_only_bbox()
    assert x1 <= 1250  # Box 29 label starts ~1252


def test_is_box28_field():
    assert is_box28_field("total_charge")
    assert is_box28_field("TOTAL_CHARGES")
    assert not is_box28_field("amount_paid")


def test_quality_lane_handwriting_requires_structured():
    decision = classify_cms1500_quality_lane(handwriting_signals=2)
    assert decision.lane is FormQualityLane.HANDWRITTEN
    assert decision.require_structured_corroboration is True
    assert decision.allow_calibrated_direct is False


def test_quality_lane_clean_printed_default():
    decision = classify_cms1500_quality_lane()
    assert decision.lane is FormQualityLane.CLEAN_PRINTED
    assert decision.allow_calibrated_direct is True


def test_box28_crop_variants_include_tight_right_band():
    variants = __import__(
        "packages.geometry_authority.box28", fromlist=["box28_crop_variants"]
    ).box28_crop_variants()
    assert len(variants) >= 2
    assert variants[0][1] >= 1825
    assert variants[1][0] > variants[0][0]


def test_form_redundancy_self_name_and_dob():
    from packages.geometry_authority.form_redundancy import (
        reconcile_box2_box4_names,
        reconcile_box3_box11a_dob,
    )

    names = reconcile_box2_box4_names(
        "Reynel, Lisa", "REYNEL LISA", relationship="SELF"
    )
    assert names.agreed and names.reason == "BOX2_BOX4_SELF_AGREE"
    dobs = reconcile_box3_box11a_dob("01/07/1980", "01071980", relationship="18")
    assert dobs.agreed and dobs.patient_iso == "1980-01-07"
