from __future__ import annotations

import re

from .models import CompiledSpecification, ParseAmbiguity, Severity
from .parser import picture_length


def validate_specification(spec: CompiledSpecification) -> list[ParseAmbiguity]:
    issues = list(spec.ambiguities)
    seen_records: set[str] = set()
    for record in spec.records:
        if record.record_type in seen_records:
            issues.append(ParseAmbiguity(
                code="duplicate_record",
                message="Record type appears more than once",
                record_type=record.record_type,
                severity=Severity.ERROR,
            ))
        seen_records.add(record.record_type)
        cursor = 1
        seen_fields: set[str] = set()
        for field in sorted(record.fields, key=lambda item: item.start_position):
            if field.field_number in seen_fields:
                issues.append(ParseAmbiguity(
                    code="duplicate_field",
                    message="Duplicate field number",
                    record_type=record.record_type,
                    field_number=field.field_number,
                    severity=Severity.ERROR,
                ))
            seen_fields.add(field.field_number)
            if field.start_position > cursor:
                issues.append(ParseAmbiguity(
                    code="unexplained_gap",
                    message=f"Unmapped positions {cursor}-{field.start_position - 1}",
                    record_type=record.record_type,
                    field_number=field.field_number,
                ))
            elif field.start_position < cursor:
                issues.append(ParseAmbiguity(
                    code="overlapping_field",
                    message=f"Field starts at {field.start_position}; cursor is {cursor}",
                    record_type=record.record_type,
                    field_number=field.field_number,
                    severity=Severity.ERROR,
                ))
            expected = picture_length(field.cobol_picture)
            if expected is not None and expected != field.calculated_length:
                # Parser may already have emitted it; keep validation idempotent.
                pass
            if field.requirement_code == "R" and not field.field_name:
                issues.append(ParseAmbiguity(
                    code="required_field_without_name",
                    message="Required field has no deterministic source name",
                    record_type=record.record_type,
                    field_number=field.field_number,
                    severity=Severity.ERROR,
                ))
            cursor = max(cursor, field.end_position + 1)
        if cursor - 1 < record.record_length:
            issues.append(ParseAmbiguity(
                code="unexplained_gap",
                message=f"Unmapped positions {cursor}-{record.record_length}",
                record_type=record.record_type,
            ))
        if cursor - 1 > record.record_length:
            issues.append(ParseAmbiguity(
                code="record_overflow",
                message=f"Fields extend to {cursor - 1}, expected {record.record_length}",
                record_type=record.record_type,
                severity=Severity.ERROR,
            ))
        for field in record.fields:
            picture = field.cobol_picture.upper()
            numeric = bool(re.search(r"(?:^|PIC\s*)[9S]", picture))
            notes = " ".join(field.formatting_notes).lower()
            if numeric and ("left justify" in notes or "blank fill" in notes):
                issues.append(ParseAmbiguity(
                    code="numeric_format_conflict",
                    message="Numeric picture conflicts with left/blank formatting note",
                    record_type=record.record_type,
                    field_number=field.field_number,
                ))
    return _deduplicate(issues)


def _deduplicate(issues: list[ParseAmbiguity]) -> list[ParseAmbiguity]:
    result: list[ParseAmbiguity] = []
    keys: set[tuple[object, ...]] = set()
    for issue in issues:
        key = (issue.code, issue.record_type, issue.field_number, issue.message)
        if key not in keys:
            keys.add(key)
            result.append(issue)
    return result

