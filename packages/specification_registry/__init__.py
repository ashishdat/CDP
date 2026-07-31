"""Specification-driven registry for legacy healthcare fixed-width formats."""

from .compiler import compile_specification
from .models import (
    CompiledSpecification,
    FieldDefinition,
    ParseAmbiguity,
    RecordDefinition,
)
from .parser import LegacyClaimSpecParser
from .registry import SpecificationRegistry
from .validator import validate_specification

__all__ = [
    "CompiledSpecification",
    "FieldDefinition",
    "LegacyClaimSpecParser",
    "ParseAmbiguity",
    "RecordDefinition",
    "SpecificationRegistry",
    "compile_specification",
    "validate_specification",
]
