"""Config-driven fixed-width record writer/reader/validator for NSF/UB92
output. Record layouts live in `config/output_specs/{nsf,ub92}/*.yaml`,
not code -- see docs/CONFIGURATION_GUIDE.md."""

from packages.fixed_width.reader import RecordLengthError, parse_record, parse_record_trimmed
from packages.fixed_width.resolver import (
    FieldResolutionError,
    resolve_field_values,
    resolve_source_field,
)
from packages.fixed_width.spec_loader import (
    load_nsf_specs,
    load_record_specs,
    load_ub92_specs,
)
from packages.fixed_width.spec_models import (
    Alignment,
    DataType,
    FixedWidthFieldSpec,
    FixedWidthRecordSpec,
)
from packages.fixed_width.validator import (
    FileStructureReport,
    RecordCountMismatch,
    SpecIssue,
    sum_numeric_field,
    validate_file_structure,
    validate_spec,
)
from packages.fixed_width.writer import FieldOverflowError, FixedWidthWriter, render_field

__all__ = [
    "Alignment",
    "DataType",
    "FieldOverflowError",
    "FieldResolutionError",
    "FileStructureReport",
    "FixedWidthFieldSpec",
    "FixedWidthRecordSpec",
    "FixedWidthWriter",
    "RecordCountMismatch",
    "RecordLengthError",
    "SpecIssue",
    "load_nsf_specs",
    "load_record_specs",
    "load_ub92_specs",
    "parse_record",
    "parse_record_trimmed",
    "render_field",
    "resolve_field_values",
    "resolve_source_field",
    "sum_numeric_field",
    "validate_file_structure",
    "validate_spec",
]
