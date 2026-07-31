"""Fixed-width record specification: the schema every NSF/UB92 record type
config file (`config/output_specs/{nsf,ub92}/*.yaml`) must conform to.

Positions are 1-indexed and inclusive, matching how both supplied spec
documents (`NSF Matrix ...`, `UB92 File Specs ...`) express "From"/"To" --
this is deliberate so a config author can transcribe a spec table directly
without an off-by-one translation step.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from packages.domain.common import DomainModel


class Alignment(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class DataType(StrEnum):
    STRING = "string"
    NUMERIC = "numeric"  # digits only, typically zero-padded, right-aligned
    DATE = "date"  # `format` gives the output picture, e.g. CCYYMMDD
    DECIMAL_IMPLIED = "decimal_implied"  # e.g. NSF 9(03)V99 -- decimal point not stored


class FixedWidthFieldSpec(DomainModel):
    field_name: str
    start_position: int = Field(ge=1)
    length: int = Field(ge=1)
    alignment: Alignment = Alignment.LEFT
    padding_character: str = " "
    data_type: DataType = DataType.STRING
    format: str | None = None
    required: bool = False
    default: str = ""
    source_field: str | None = None  # dotted attribute path into the canonical Claim

    @property
    def end_position(self) -> int:
        return self.start_position + self.length - 1

    @model_validator(mode="after")
    def _padding_character_is_one_char(self) -> FixedWidthFieldSpec:
        if len(self.padding_character) != 1:
            raise ValueError(
                f"{self.field_name}: padding_character must be exactly one character, "
                f"got {self.padding_character!r}"
            )
        return self


class FixedWidthRecordSpec(DomainModel):
    record_type: str
    record_length: int = Field(ge=1)
    fields: list[FixedWidthFieldSpec]

    def field(self, name: str) -> FixedWidthFieldSpec:
        for f in self.fields:
            if f.field_name == name:
                return f
        raise KeyError(f"{self.record_type}: no field named {name!r}")
