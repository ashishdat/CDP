"""Config-driven fixed-width record writer.

`render_record` is the only thing that produces output bytes -- it takes
already-resolved `{field_name: value}` pairs (see `resolver.py` for
pulling those out of a canonical `Claim`) and a `FixedWidthRecordSpec`,
and returns an exact-length record string. Every byte position in the
record must be covered by exactly one field in the spec (enforced by
`FixedWidthValidator.validate_spec`, not here) -- this writer trusts the
spec once it's validated.
"""

from __future__ import annotations

import re

from packages.fixed_width.spec_models import (
    Alignment,
    DataType,
    FixedWidthFieldSpec,
    FixedWidthRecordSpec,
)

RECORD_TERMINATOR = "\r\n"  # matches the supplied reference outputs (CRLF, ASCII)


class FieldOverflowError(ValueError):
    """Raised when a resolved value doesn't fit in its field, for data
    types where silent truncation would corrupt meaning (numeric/date) --
    text fields truncate per the NSF spec's own "truncate if necessary"
    convention instead of raising."""


def render_field(spec: FixedWidthFieldSpec, raw_value: str | None) -> str:
    value = spec.default if raw_value is None or raw_value == "" else str(raw_value)

    if spec.data_type in (DataType.NUMERIC, DataType.DECIMAL_IMPLIED):
        # DECIMAL_IMPLIED (e.g. NSF 9(03)V99): the decimal point is not
        # stored, only its digits are -- stripping all non-digits handles
        # both cases identically.
        digits = re.sub(r"[^0-9]", "", value)
        if len(digits) > spec.length:
            raise FieldOverflowError(
                f"{spec.field_name}: numeric value {value!r} ({len(digits)} digits) "
                f"exceeds field length {spec.length}"
            )
        pad_char = spec.padding_character
        return digits.rjust(spec.length, pad_char)

    if spec.data_type is DataType.DATE:
        if len(value) != spec.length and value != spec.default:
            raise FieldOverflowError(
                f"{spec.field_name}: date value {value!r} does not match expected "
                f"length {spec.length} for format {spec.format}"
            )
        return value.ljust(spec.length, spec.padding_character)[: spec.length]

    # STRING
    truncated = value[: spec.length]
    if spec.alignment is Alignment.RIGHT:
        return truncated.rjust(spec.length, spec.padding_character)
    return truncated.ljust(spec.length, spec.padding_character)


class FixedWidthWriter:
    def __init__(self, spec: FixedWidthRecordSpec) -> None:
        self._spec = spec

    def render_record(self, field_values: dict[str, str]) -> str:
        ordered = sorted(self._spec.fields, key=lambda f: f.start_position)
        parts = [render_field(field, field_values.get(field.field_name)) for field in ordered]
        record = "".join(parts)
        if len(record) != self._spec.record_length:
            raise FieldOverflowError(
                f"{self._spec.record_type}: rendered record is {len(record)} bytes, "
                f"expected {self._spec.record_length}"
            )
        return record

    def render_line(self, field_values: dict[str, str]) -> str:
        return self.render_record(field_values) + RECORD_TERMINATOR
