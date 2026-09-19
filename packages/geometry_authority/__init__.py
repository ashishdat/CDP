"""Semantic geometry authority for fixed-form CMS-1500 / UB-04 regions."""

from .cms1500_regions import (
    CMS1500_BOX28,
    CMS1500_LINE_COLUMNS,
    RegionVerdict,
    box28_contains,
    charge_region_verdict,
    is_pos_like_currency,
    reject_pos_as_charge,
)

__all__ = [
    "CMS1500_BOX28",
    "CMS1500_LINE_COLUMNS",
    "RegionVerdict",
    "box28_contains",
    "charge_region_verdict",
    "is_pos_like_currency",
    "reject_pos_as_charge",
]
