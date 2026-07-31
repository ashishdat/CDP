"""Inverse of `writer.py`: parse a fixed-width record line into
`{field_name: raw_string}` per a `FixedWidthRecordSpec`. Values are
returned exactly as stored (still padded) -- callers that want trimmed/
typed values should strip/normalize per `data_type` themselves (this
mirrors `writer.render_field` not doing normalization either; parsing and
business-value normalization are kept separate on purpose)."""

from __future__ import annotations

from packages.fixed_width.spec_models import FixedWidthRecordSpec


class RecordLengthError(ValueError):
    pass


def parse_record(spec: FixedWidthRecordSpec, line: str) -> dict[str, str]:
    if len(line) != spec.record_length:
        raise RecordLengthError(
            f"{spec.record_type}: line is {len(line)} bytes, expected {spec.record_length}"
        )
    return {
        field.field_name: line[field.start_position - 1 : field.end_position]
        for field in spec.fields
    }


def parse_record_trimmed(spec: FixedWidthRecordSpec, line: str) -> dict[str, str]:
    return {name: value.strip() for name, value in parse_record(spec, line).items()}
