"""CMS-1500 Box 28 (total charge) value-only crop helpers.

The printed caption ``28. TOTAL CHARGE`` sits at the top of Box 28; the amount is
below it, right-aligned against the dollars|cents dashed ruling. Using the full
cell without caption exclusion, or a ROI that lands in Box 29, yields blank /
ruling-only OCR and false EMPTY_FINANCIAL_INK.

Measured against warped Hackathon pages (cms1500@03, 1712×2214):

- caption band ~1805–1825
- value ink ~1825–1872 (tall amounts such as 4972 sit near 1851–1872)
- Box 29 starts ~1250
"""

from __future__ import annotations

# Reference pixels for cms1500@03. y1 must clear tall printed totals (e.g. 4972).
CMS1500_BOX28_FULL: tuple[int, int, int, int] = (1045, 1805, 1248, 1875)
CMS1500_BOX28_CAPTION_PX = 20


def box28_value_only_bbox(
    full: tuple[int, int, int, int] | None = None,
    *,
    caption_px: int = CMS1500_BOX28_CAPTION_PX,
) -> tuple[int, int, int, int]:
    """Return Box 28 ROI with the printed caption strip removed."""
    x0, y0, x1, y1 = full or CMS1500_BOX28_FULL
    top = min(y1 - 1, y0 + max(0, int(caption_px)))
    return (int(x0), int(top), int(x1), int(y1))


def box28_crop_variants(
    full: tuple[int, int, int, int] | None = None,
) -> tuple[tuple[int, int, int, int], ...]:
    """Ordered value crops: primary caption-excluded, then tight right-aligned."""
    primary = box28_value_only_bbox(full)
    x0, y0, x1, y1 = primary
    # Right-biased value band — reduces caption/left-$ bleed (e.g. 81.00 vs 8T:00).
    tight = (
        min(x1 - 1, x0 + 35),
        min(y1 - 1, y0 + 3),
        x1,
        y1,
    )
    taller = (x0, max(0, y0 - 5), x1, y1)
    return (primary, tight, taller)


def is_box28_field(field_name: object) -> bool:
    key = str(field_name or "").strip().casefold()
    return key in {"total_charge", "total_charges"}
