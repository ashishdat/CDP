"""Post-registration content checks against CMS-1500 landmark labels.

Rejects warps that place insurance-type text into patient identity boxes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from PIL import Image

_INSURANCE_TOKENS = ("MEDICARE", "MEDICAID", "TRICARE", "CHAMPVA", "FECA")
_NAME_LABEL_TOKENS = ("PATIENT", "NAME")
_DOB_LABEL_TOKENS = ("BIRTH", "DATE", "MM", "DD", "YY")


@dataclass(frozen=True)
class ContentValidationResult:
    accepted: bool
    reason: str
    patient_name_text: str = ""
    patient_dob_text: str = ""


def _ocr_region(image: Image.Image, box: tuple[int, int, int, int]) -> str:
    from workers.cascade.tesseract_adapter import TesseractTextExtractor

    x0, y0, x1, y1 = box
    crop = image.crop((x0, y0, x1, y1))
    lines = TesseractTextExtractor(psm=6).extract(crop)
    return " ".join(str(line.text if hasattr(line, "text") else line) for line in lines).upper()


def validate_cms1500_registration_content(
    warped: Image.Image,
    *,
    patient_name_box: tuple[int, int, int, int],
    patient_dob_box: tuple[int, int, int, int],
) -> ContentValidationResult:
    """Return accepted=False when identity ROIs still read insurance-type labels."""
    name_text = _ocr_region(warped, patient_name_box)
    dob_text = _ocr_region(warped, patient_dob_box)
    insurance_hits = sum(1 for token in _INSURANCE_TOKENS if token in name_text or token in dob_text)
    name_label_hits = sum(1 for token in _NAME_LABEL_TOKENS if token in name_text)
    # Blank forms OCR the printed label ("2. PATIENT'S NAME"); filled forms OCR the value.
    # Reject only when insurance-type vocabulary dominates the identity boxes.
    if insurance_hits >= 2 and name_label_hits == 0:
        return ContentValidationResult(
            False,
            "IDENTITY_ROI_READS_INSURANCE_TYPE_ROW",
            name_text,
            dob_text,
        )
    if re.search(r"\bMEDICARE\b", name_text) and re.search(r"\bCHAMPVA\b", dob_text):
        return ContentValidationResult(
            False,
            "IDENTITY_ROI_READS_INSURANCE_TYPE_ROW",
            name_text,
            dob_text,
        )
    return ContentValidationResult(True, "CONTENT_LANDMARKS_PLAUSIBLE", name_text, dob_text)
