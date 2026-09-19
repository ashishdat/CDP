"""Semantic geometry authority for fixed-form CMS-1500 / UB-04 regions."""

from .box28 import (
    CMS1500_BOX28_FULL,
    box28_crop_variants,
    box28_value_only_bbox,
    is_box28_field,
)
from .cms1500_regions import (
    CMS1500_BOX28,
    CMS1500_LINE_COLUMNS,
    RegionVerdict,
    box28_contains,
    charge_region_verdict,
    is_pos_like_currency,
    reject_pos_as_charge,
)
from .form_redundancy import (
    reconcile_box2_box4_names,
    reconcile_box3_box11a_dob,
)
from .quality_lanes import (
    FormQualityLane,
    QualityLaneDecision,
    classify_cms1500_quality_lane,
)

__all__ = [
    "CMS1500_BOX28",
    "CMS1500_BOX28_FULL",
    "CMS1500_LINE_COLUMNS",
    "FormQualityLane",
    "QualityLaneDecision",
    "RegionVerdict",
    "box28_contains",
    "box28_crop_variants",
    "box28_value_only_bbox",
    "charge_region_verdict",
    "classify_cms1500_quality_lane",
    "is_box28_field",
    "is_pos_like_currency",
    "reconcile_box2_box4_names",
    "reconcile_box3_box11a_dob",
    "reject_pos_as_charge",
]
