"""Required-field validation against a template's `required_fields` list."""

from __future__ import annotations

from packages.domain.extraction import ExtractedField


def find_missing_required_fields(
    required_field_names: list[str], extracted_fields: list[ExtractedField]
) -> list[str]:
    by_name = {f.field_name: f for f in extracted_fields}
    missing = []
    for name in required_field_names:
        field = by_name.get(name)
        if field is None or not field.raw_value.strip():
            missing.append(name)
    return missing
