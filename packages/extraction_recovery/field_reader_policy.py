"""Which OCR engine or model may read each critical CMS-1500 field.

Local printed OCR accepts the field. A cloud crop may confirm that ink.
Only person names may be replaced by the crop. Charges never straight-through
on Claude, gpt-4o, or Tesseract alone. Azure Document Intelligence is not
on this path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldReader:
    field: str
    local_ocr: tuple[str, ...]
    local_residual: str | None
    model: str | None
    model_may_supersede: bool


_READERS: dict[str, FieldReader] = {
    "patient_dob": FieldReader(
        "patient_dob",
        ("tesseract_digits", "paddleocr", "rapidocr"),
        "trocr",
        "claude",
        False,
    ),
    "insured_dob": FieldReader(
        "insured_dob",
        ("tesseract_digits", "paddleocr", "rapidocr"),
        "trocr",
        "claude",
        False,
    ),
    "patient_name": FieldReader(
        "patient_name",
        ("rapidocr", "paddleocr"),
        None,
        "claude",
        True,
    ),
    "insured_name": FieldReader(
        "insured_name",
        ("rapidocr", "paddleocr"),
        None,
        "claude",
        True,
    ),
    "insured_id_number": FieldReader(
        "insured_id_number",
        ("paddleocr", "rapidocr"),
        None,
        "claude",
        False,
    ),
    "total_charge": FieldReader(
        "total_charge",
        ("paddleocr", "rapidocr"),
        "tesseract_digits",
        "claude",
        False,
    ),
    "charges": FieldReader(
        "charges",
        ("paddleocr", "rapidocr"),
        "tesseract_digits",
        "claude",
        False,
    ),
}

_ALIASES = {
    "date_of_birth": "patient_dob",
    "member_id": "insured_id_number",
    "subscriber_id": "insured_id_number",
    "total_charges": "total_charge",
    "charge_amount": "charges",
}


def reader_for(field_name: object) -> FieldReader | None:
    key = str(field_name or "").strip().casefold()
    key = _ALIASES.get(key, key)
    return _READERS.get(key)


def azure_di_on_path(field_name: object) -> bool:
    """Document Intelligence is not a reader for any critical field."""
    del field_name
    return False


def model_may_supersede(field_name: object) -> bool:
    reader = reader_for(field_name)
    return bool(reader and reader.model_may_supersede)
