"""Field-specific OCR crop insets for contaminated CMS-1500 template ROIs.

Geometry still records the full safe cell. These insets shrink the OCR window
inside that cell so printed labels / neighboring NPI columns are excluded
without requiring a fresh registration.
"""

from __future__ import annotations

from typing import Mapping

# Fractions of (width, height) trimmed from each edge of the aligned ROI.
# Values are chosen from live crops where patient_dob captured "3. PATIENT'S
# BIRTH DATE / MM DD YY" and total_charge captured the box-33 NPI legend.
ROI_INSETS: Mapping[str, Mapping[str, float]] = {
    # Template ROI is already the digit band; light top trim only. Keep clear of patient_sex at x1=886.
    "patient_dob": {"top": 0.42, "right": 0.10, "bottom": 0.02, "left": 0.02},
    # Pull away from the NPI column bleed on the left/bottom of box 28.
    "total_charge": {"top": 0.12, "right": 0.04, "bottom": 0.06, "left": 0.24},
}


def inset_bbox(
    bbox: tuple[int, int, int, int],
    field_name: str,
    *,
    min_width: int = 12,
    min_height: int = 10,
) -> tuple[int, int, int, int]:
    """Return an integer pixel bbox shrunk by the field inset, if configured."""
    insets = ROI_INSETS.get(field_name)
    if not insets:
        return bbox
    x0, y0, x1, y1 = bbox
    width = x1 - x0
    height = y1 - y0
    if width <= min_width or height <= min_height:
        return bbox
    nx0 = x0 + int(round(width * float(insets.get("left", 0.0))))
    ny0 = y0 + int(round(height * float(insets.get("top", 0.0))))
    nx1 = x1 - int(round(width * float(insets.get("right", 0.0))))
    ny1 = y1 - int(round(height * float(insets.get("bottom", 0.0))))
    if nx1 - nx0 < min_width or ny1 - ny0 < min_height:
        return bbox
    return (nx0, ny0, nx1, ny1)
