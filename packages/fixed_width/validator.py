"""Structural validation for fixed-width specs and generated output:
record length, field position coverage (no gaps/overlaps), record counts,
and financial-total reconciliation. Deterministic, no I/O beyond what's
passed in -- this is what `tests/golden` runs against real reference
output, and what output_generation (Phase 3 worker, not yet wired) will
run before considering a file final.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.fixed_width.reader import parse_record_trimmed
from packages.fixed_width.spec_models import FixedWidthRecordSpec


@dataclass
class SpecIssue:
    record_type: str
    message: str


def validate_spec(spec: FixedWidthRecordSpec) -> list[SpecIssue]:
    """Every byte position 1..record_length must be covered by exactly one
    field -- gaps silently drop data, overlaps silently corrupt it."""
    issues: list[SpecIssue] = []
    ordered = sorted(spec.fields, key=lambda f: f.start_position)

    cursor = 1
    for f in ordered:
        if f.start_position > cursor:
            issues.append(
                SpecIssue(
                    spec.record_type,
                    f"gap of {f.start_position - cursor} byte(s) before field "
                    f"'{f.field_name}' (positions {cursor}-{f.start_position - 1} unmapped)",
                )
            )
        elif f.start_position < cursor:
            issues.append(
                SpecIssue(
                    spec.record_type,
                    f"field '{f.field_name}' starts at {f.start_position}, overlapping "
                    f"the previous field which ends at {cursor - 1}",
                )
            )
        cursor = max(cursor, f.end_position + 1)

    if cursor - 1 != spec.record_length:
        issues.append(
            SpecIssue(
                spec.record_type,
                f"fields cover positions up to {cursor - 1}, but record_length is "
                f"{spec.record_length}",
            )
        )
    return issues


@dataclass
class RecordCountMismatch:
    record_type: str
    expected: int
    actual: int


@dataclass
class FileStructureReport:
    record_counts: dict[str, int] = field(default_factory=dict)
    length_mismatches: list[str] = field(default_factory=list)
    count_mismatches: list[RecordCountMismatch] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.length_mismatches and not self.count_mismatches


def validate_file_structure(
    lines: list[str],
    specs_by_record_type: dict[str, FixedWidthRecordSpec],
    expected_counts: dict[str, int] | None = None,
) -> FileStructureReport:
    report = FileStructureReport()
    for line_number, line in enumerate(lines, start=1):
        record_type = line[:3].strip() if len(line) >= 3 else line.strip()
        # NSF record IDs are 3 chars; UB92 are 2 -- try the longest match
        # among configured record types that this line's prefix starts with.
        matched = next(
            (rt for rt in specs_by_record_type if line.startswith(rt)),
            record_type,
        )
        spec = specs_by_record_type.get(matched)
        report.record_counts[matched] = report.record_counts.get(matched, 0) + 1
        if spec is not None and len(line) != spec.record_length:
            report.length_mismatches.append(
                f"line {line_number} ({matched}): {len(line)} bytes, expected {spec.record_length}"
            )

    if expected_counts:
        for record_type, expected in expected_counts.items():
            actual = report.record_counts.get(record_type, 0)
            if actual != expected:
                report.count_mismatches.append(
                    RecordCountMismatch(record_type, expected, actual)
                )

    return report


def sum_numeric_field(spec: FixedWidthRecordSpec, field_name: str, lines: list[str]) -> int:
    """Sum a numeric (or decimal-implied) field across every line matching
    `spec.record_type`, returned as an integer in the field's smallest
    stored unit (e.g. cents, for a decimal-implied currency field) so
    reconciling claim/service-line totals never involves float rounding."""
    total = 0
    for line in lines:
        if not line.startswith(spec.record_type):
            continue
        values = parse_record_trimmed(spec, line)
        raw = values.get(field_name, "")
        total += int(raw) if raw else 0
    return total
