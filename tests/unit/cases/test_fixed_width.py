"""Fixed-width engine: writer/reader round-trip, overflow/truncation
behavior, spec validation (gap/overlap detection), and source-field
resolution -- synthetic specs, so these are independent of the real
NSF/UB92 configs (covered for real data in tests/golden)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from packages.fixed_width.reader import RecordLengthError, parse_record, parse_record_trimmed
from packages.fixed_width.resolver import FieldResolutionError, resolve_source_field
from packages.fixed_width.spec_models import (
    Alignment,
    DataType,
    FixedWidthFieldSpec,
    FixedWidthRecordSpec,
)
from packages.fixed_width.validator import validate_spec
from packages.fixed_width.writer import FieldOverflowError, FixedWidthWriter, render_field


def _spec(*fields: FixedWidthFieldSpec, record_type="TT0", length=None) -> FixedWidthRecordSpec:
    total = length if length is not None else sum(f.length for f in fields)
    return FixedWidthRecordSpec(record_type=record_type, record_length=total, fields=list(fields))


def test_string_field_left_justifies_and_space_pads():
    field = FixedWidthFieldSpec(field_name="name", start_position=1, length=10)
    assert render_field(field, "AB") == "AB        "


def test_string_field_right_aligned():
    field = FixedWidthFieldSpec(
        field_name="name", start_position=1, length=10, alignment=Alignment.RIGHT
    )
    assert render_field(field, "AB") == "        AB"


def test_string_field_truncates_long_values():
    field = FixedWidthFieldSpec(field_name="name", start_position=1, length=4)
    assert render_field(field, "TOOLONGVALUE") == "TOOL"


def test_numeric_field_right_justifies_zero_padded():
    field = FixedWidthFieldSpec(
        field_name="amount", start_position=1, length=6, data_type=DataType.NUMERIC,
        padding_character="0",
    )
    assert render_field(field, "175") == "000175"


def test_numeric_field_strips_non_digits():
    field = FixedWidthFieldSpec(
        field_name="amount", start_position=1, length=6, data_type=DataType.NUMERIC,
        padding_character="0",
    )
    assert render_field(field, "$1,675.00") == "167500"


def test_numeric_field_overflow_raises():
    field = FixedWidthFieldSpec(
        field_name="amount", start_position=1, length=3, data_type=DataType.NUMERIC
    )
    with pytest.raises(FieldOverflowError):
        render_field(field, "12345")


def test_date_field_wrong_length_raises():
    """The writer enforces *length* (a malformed-but-right-length date
    string is a validation concern, not a serialization one -- see
    packages/validation_rules in Phase 3)."""
    field = FixedWidthFieldSpec(
        field_name="dob", start_position=1, length=8, data_type=DataType.DATE, format="CCYYMMDD"
    )
    with pytest.raises(FieldOverflowError):
        render_field(field, "2025716")  # only 7 characters


def test_empty_value_falls_back_to_default():
    field = FixedWidthFieldSpec(field_name="x", start_position=1, length=4, default="ABCD")
    assert render_field(field, None) == "ABCD"
    assert render_field(field, "") == "ABCD"


def test_record_renders_at_exact_length_and_position_order():
    spec = _spec(
        FixedWidthFieldSpec(field_name="a", start_position=1, length=3),
        FixedWidthFieldSpec(field_name="b", start_position=4, length=5),
    )
    writer = FixedWidthWriter(spec)
    record = writer.render_record({"a": "XY", "b": "12345"})
    assert record == "XY 12345"
    assert len(record) == spec.record_length


def test_render_line_appends_crlf():
    spec = _spec(FixedWidthFieldSpec(field_name="a", start_position=1, length=3))
    writer = FixedWidthWriter(spec)
    assert writer.render_line({"a": "XY"}) == "XY \r\n"


def test_writer_and_reader_are_inverses_for_arbitrary_values():
    spec = _spec(
        FixedWidthFieldSpec(field_name="a", start_position=1, length=3),
        FixedWidthFieldSpec(
            field_name="b", start_position=4, length=5, data_type=DataType.NUMERIC,
            padding_character="0",
        ),
    )
    writer = FixedWidthWriter(spec)
    record = writer.render_record({"a": "Z", "b": "42"})
    parsed = parse_record(spec, record)
    assert parsed == {"a": "Z  ", "b": "00042"}


def test_reader_rejects_wrong_length_line():
    spec = _spec(FixedWidthFieldSpec(field_name="a", start_position=1, length=3))
    with pytest.raises(RecordLengthError):
        parse_record(spec, "TOO LONG")


def test_parse_record_trimmed_strips_whitespace():
    spec = _spec(FixedWidthFieldSpec(field_name="a", start_position=1, length=6))
    assert parse_record_trimmed(spec, "  hi  ") == {"a": "hi"}


def test_validate_spec_detects_gap():
    spec = _spec(
        FixedWidthFieldSpec(field_name="a", start_position=1, length=3),
        FixedWidthFieldSpec(field_name="b", start_position=6, length=3),
        length=8,
    )
    issues = validate_spec(spec)
    assert len(issues) >= 1
    assert any("gap" in i.message for i in issues)


def test_validate_spec_detects_overlap():
    spec = _spec(
        FixedWidthFieldSpec(field_name="a", start_position=1, length=5),
        FixedWidthFieldSpec(field_name="b", start_position=3, length=3),
        length=5,
    )
    issues = validate_spec(spec)
    assert any("overlap" in i.message for i in issues)


def test_validate_spec_detects_length_mismatch():
    spec = _spec(FixedWidthFieldSpec(field_name="a", start_position=1, length=3), length=10)
    issues = validate_spec(spec)
    assert any("record_length" in i.message for i in issues)


def test_validate_spec_passes_for_contiguous_fields():
    spec = _spec(
        FixedWidthFieldSpec(field_name="a", start_position=1, length=3),
        FixedWidthFieldSpec(field_name="b", start_position=4, length=5),
    )
    assert validate_spec(spec) == []


@dataclass
class _FakeProvider:
    tax_id: str


@dataclass
class _FakeClaim:
    provider: _FakeProvider
    total_charge: Decimal
    service_date: date


def test_resolve_source_field_simple_attribute():
    claim = _FakeClaim(_FakeProvider("721216996"), Decimal("175.00"), date(2025, 7, 16))
    assert resolve_source_field(claim, "provider.tax_id") == "721216996"


def test_resolve_source_field_formats_date_as_ccyymmdd():
    claim = _FakeClaim(_FakeProvider("x"), Decimal(0), date(2025, 7, 16))
    assert resolve_source_field(claim, "service_date") == "20250716"


def test_resolve_source_field_formats_decimal_as_implied_cents():
    claim = _FakeClaim(_FakeProvider("x"), Decimal("175.00"), date(2025, 1, 1))
    assert resolve_source_field(claim, "total_charge") == "17500"


def test_resolve_source_field_missing_attribute_raises():
    claim = _FakeClaim(_FakeProvider("x"), Decimal(0), date(2025, 1, 1))
    with pytest.raises(FieldResolutionError):
        resolve_source_field(claim, "provider.does_not_exist")


def test_resolve_source_field_none_intermediate_returns_empty_string():
    @dataclass
    class Wrapper:
        provider: _FakeProvider | None

    assert resolve_source_field(Wrapper(None), "provider.tax_id") == ""
