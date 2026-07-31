from __future__ import annotations

import re
from pathlib import Path

from .models import (
    CompiledSpecification,
    FieldDefinition,
    ParseAmbiguity,
    RecordDefinition,
    Severity,
)

_RECORD = re.compile(
    r"^\s*Record\s+Type:\s*(?P<type>[A-Z0-9]{2,3})"
    r"(?:\s+Record\s+Name:\s*|\s+)(?P<name>.+?)\s*$",
    re.IGNORECASE,
)
_FIELD = re.compile(
    r"^\s*(?P<number>\d{1,3}(?:\.\d+)?)\.?\s+"
    r"(?P<start>\d{1,3})\s+(?P<end>\d{1,3})\s+"
    r"(?P<picture>(?:PIC\s+)?[X9S][A-Z0-9()V.+\-]*)\s+"
    r"(?P<requirement>[RCON])\s+(?P<name>.+?)\s*$",
    re.IGNORECASE,
)
_PICTURE_LENGTH = re.compile(r"([X9])\((\d+)\)", re.IGNORECASE)


def picture_length(picture: str) -> int | None:
    normalized = picture.upper().replace("PIC", "").replace(" ", "")
    pieces = _PICTURE_LENGTH.findall(normalized)
    if pieces:
        remainder = _PICTURE_LENGTH.sub("", normalized)
        return sum(int(length) for _, length in pieces) + sum(
            char in {"X", "9"} for char in remainder
        )
    symbols = [char for char in normalized if char in {"X", "9"}]
    return len(symbols) or None


class LegacyClaimSpecParser:
    """Parse the deterministic record/field tables from LibreOffice text output."""

    def parse(
        self,
        text: str,
        *,
        format_name: str,
        version: str,
        source_document: str,
        record_length: int,
    ) -> CompiledSpecification:
        records: list[RecordDefinition] = []
        ambiguities: list[ParseAmbiguity] = []
        current: RecordDefinition | None = None
        current_field: FieldDefinition | None = None
        preamble: list[str] = []

        for line_number, raw in enumerate(text.splitlines(), start=1):
            line = re.sub(r"\s+", " ", raw).strip()
            if not line:
                continue
            record_match = _RECORD.match(line)
            if record_match:
                current = RecordDefinition(
                    record_type=record_match.group("type").upper(),
                    record_name=record_match.group("name").strip(),
                    record_length=record_length,
                    order=len(records),
                    record_rules=preamble[-10:],
                )
                records.append(current)
                current_field = None
                preamble = []
                continue
            if current is None:
                preamble.append(line)
                continue
            field_match = _FIELD.match(line)
            if field_match:
                start = int(field_match.group("start"))
                end = int(field_match.group("end"))
                current_field = FieldDefinition(
                    field_number=field_match.group("number"),
                    start_position=start,
                    end_position=end,
                    cobol_picture=field_match.group("picture").upper(),
                    requirement_code=field_match.group("requirement").upper(),
                    field_name=field_match.group("name").strip(" ."),
                    source_line=line_number,
                )
                current.fields.append(current_field)
                expected = picture_length(current_field.cobol_picture)
                if expected is None:
                    ambiguities.append(ParseAmbiguity(
                        code="unsupported_picture",
                        message=f"Unsupported COBOL picture {current_field.cobol_picture!r}",
                        record_type=current.record_type,
                        field_number=current_field.field_number,
                        source_line=line_number,
                    ))
                elif expected != current_field.calculated_length:
                    ambiguities.append(ParseAmbiguity(
                        code="inconsistent_length",
                        message=(
                            f"positions imply {current_field.calculated_length}, "
                            f"picture implies {expected}"
                        ),
                        record_type=current.record_type,
                        field_number=current_field.field_number,
                        source_line=line_number,
                        severity=Severity.ERROR,
                    ))
                continue
            if current_field is not None:
                current_field.description = (
                    f"{current_field.description} {line}".strip()
                )
                lowered = line.lower()
                if "must be" in lowered or "valid values" in lowered:
                    current_field.allowed_values.append(line)
                if "if " in lowered or "when " in lowered:
                    current_field.conditional_rules.append(line)
                if any(token in lowered for token in ("justify", "fill", "format", "date")):
                    current_field.formatting_notes.append(line)
            elif "preced" in line.lower():
                current.preceding_rules.append(line)
            elif "follow" in line.lower():
                current.following_rules.append(line)
            else:
                current.record_rules.append(line)

        records = self._merge_repeated_page_sections(records, ambiguities)
        for record in records:
            if not record.fields:
                ambiguities.append(ParseAmbiguity(
                    code="record_without_fields",
                    message="No deterministic field rows parsed",
                    record_type=record.record_type,
                    severity=Severity.ERROR,
                ))
        return CompiledSpecification(
            format_name=format_name,
            version=version,
            source_document=source_document,
            record_length=record_length,
            records=records,
            ambiguities=ambiguities,
        )

    @staticmethod
    def _merge_repeated_page_sections(
        records: list[RecordDefinition],
        ambiguities: list[ParseAmbiguity],
    ) -> list[RecordDefinition]:
        """Legacy conversion repeats the record heading at each page break."""
        merged: dict[str, RecordDefinition] = {}
        ordered: list[RecordDefinition] = []
        for section in records:
            record = merged.get(section.record_type)
            if record is None:
                section.order = len(ordered)
                merged[section.record_type] = section
                ordered.append(section)
                continue
            record.record_rules.extend(section.record_rules)
            record.preceding_rules.extend(section.preceding_rules)
            record.following_rules.extend(section.following_rules)
            by_number = {field.field_number: field for field in record.fields}
            for field in section.fields:
                existing = by_number.get(field.field_number)
                if existing is None:
                    record.fields.append(field)
                    by_number[field.field_number] = field
                elif (
                    existing.start_position,
                    existing.end_position,
                    existing.cobol_picture,
                ) != (
                    field.start_position,
                    field.end_position,
                    field.cobol_picture,
                ):
                    ambiguities.append(ParseAmbiguity(
                        code="duplicate_field_conflict",
                        message=(
                            "Repeated page section defines the field differently: "
                            f"{existing.start_position}-{existing.end_position} versus "
                            f"{field.start_position}-{field.end_position}"
                        ),
                        record_type=record.record_type,
                        field_number=field.field_number,
                        source_line=field.source_line,
                        severity=Severity.ERROR,
                    ))
        return ordered

    def parse_file(self, path: Path, **metadata: object) -> CompiledSpecification:
        return self.parse(path.read_text(encoding="utf-8"), **metadata)
