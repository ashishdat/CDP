from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class Severity(StrEnum):
    ERROR = "error"
    REVIEW = "review"


class ParseAmbiguity(BaseModel):
    code: str
    message: str
    record_type: str | None = None
    field_number: str | None = None
    source_line: int | None = None
    severity: Severity = Severity.REVIEW


class FieldDefinition(BaseModel):
    field_number: str
    start_position: int = Field(ge=1)
    end_position: int = Field(ge=1)
    cobol_picture: str
    requirement_code: str
    field_name: str
    description: str = ""
    allowed_values: list[str] = Field(default_factory=list)
    conditional_rules: list[str] = Field(default_factory=list)
    formatting_notes: list[str] = Field(default_factory=list)
    source_line: int | None = None

    @computed_field
    @property
    def calculated_length(self) -> int:
        return self.end_position - self.start_position + 1


class RecordDefinition(BaseModel):
    record_type: str
    record_name: str
    record_length: int
    order: int
    preceding_rules: list[str] = Field(default_factory=list)
    following_rules: list[str] = Field(default_factory=list)
    record_rules: list[str] = Field(default_factory=list)
    fields: list[FieldDefinition] = Field(default_factory=list)


class CompiledSpecification(BaseModel):
    format_name: str
    version: str
    source_document: str
    record_length: int
    records: list[RecordDefinition]
    ambiguities: list[ParseAmbiguity] = Field(default_factory=list)

