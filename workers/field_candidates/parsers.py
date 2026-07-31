"""Deterministic constrained alternatives emitted after regional OCR."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


def parse_alternatives(field_name: str, raw: str) -> list[tuple[str, tuple[str, ...]]]:
    value = raw.strip()
    if not value:
        return []
    if field_name in {"patient_first", "patient_last"}:
        parts = []
        for component in re.split(r"[,.;|]+|\s{2,}", value):
            cleaned = re.sub(r"[^A-Za-z' -]", "", component).strip()
            if cleaned:
                parts.append(cleaned)
        if len(parts) >= 2:
            selected = parts[0] if field_name == "patient_last" else parts[1].split()[0]
            normalized = selected.upper()
            alternatives = [(normalized, ("person_name_component",))]
            width = 20 if field_name == "patient_last" else 9
            if len(normalized) > width:
                alternatives.append((
                    normalized[:width],
                    ("person_name_component", "fixed_width_output_projection"),
                ))
            return alternatives
    if field_name == "provider_npi":
        digits = re.sub(r"\D", "", value)
        return [(digits, ("ten_digits", "npi_checksum"))] if _valid_npi(digits) else []
    if field_name in {"federal_tax_id", "federal_tax_no"}:
        digits = re.sub(r"\D", "", value)
        return [(digits, ("nine_digit_tax_id",))] if len(digits) == 9 else []
    if field_name in {"patient_zip", "insured_zip"}:
        digits = re.sub(r"\D", "", value)
        return [(digits, ("zip_length",))] if len(digits) in {5, 9} else []
    if field_name == "patient_dob":
        digits = re.sub(r"\D", "", value)
        formats = ("%m%d%Y", "%Y%m%d", "%m%d%y")
        for fmt in formats:
            try:
                datetime.strptime(digits, fmt)  # noqa: DTZ007
                return [(digits, ("valid_calendar_date",))]
            except ValueError:
                continue
        return []
    if field_name == "type_of_bill":
        code = re.sub(r"\D", "", value)
        if len(code) == 4 and code.startswith("0"):
            code = code[1:]
        return [(code, ("three_digit_bill_type",))] if len(code) == 3 else []
    if field_name == "principal_diagnosis":
        code = re.sub(r"[^A-Z0-9.]", "", value.upper())
        return [(code, ("diagnosis_format",))] if re.fullmatch(r"[A-Z0-9][A-Z0-9.]{2,7}", code) else []
    if field_name == "patient_control_number":
        identifier = re.sub(r"[^A-Z0-9]", "", value.upper())
        return [(identifier, ("identifier_format",))] if identifier else []
    if field_name in {"total_charge", "total_charges"}:
        cleaned = re.sub(r"[^0-9.\-]", "", value)
        try:
            return [(format(Decimal(cleaned), ".2f"), ("valid_decimal",))]
        except InvalidOperation:
            return []
    normalized = re.sub(r"\s+", " ", value).strip()
    return [(normalized, ("non_empty",))]


def _valid_npi(value: str) -> bool:
    if len(value) != 10:
        return False
    payload = "80840" + value[:-1]
    total = 0
    for index, digit in enumerate(reversed(payload)):
        number = int(digit) * (2 if index % 2 == 0 else 1)
        total += number // 10 + number % 10
    check = (10 - total % 10) % 10
    return check == int(value[-1])
