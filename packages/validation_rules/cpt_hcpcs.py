"""CPT (Category I, 5 digits) and HCPCS Level II (1 letter + 4 digits)
procedure code validation: syntax always checked; a reference lookup
(does this code exist / is it active / bundling rules) is a separate,
optional adapter -- same pattern as `icd10.py`. Verified against real
procedure codes from the supplied dataset (96116, 96132, 96133, 96136,
96137 -- see docs/DATASET_FINDINGS.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_CPT_PATTERN = re.compile(r"^\d{5}$")
_HCPCS_LEVEL_II_PATTERN = re.compile(r"^[A-Z]\d{4}$")
_MODIFIER_PATTERN = re.compile(r"^[A-Z0-9]{2}$")


def is_valid_cpt_syntax(code: str) -> bool:
    return bool(_CPT_PATTERN.match(code.strip().upper()))


def is_valid_hcpcs_syntax(code: str) -> bool:
    cleaned = code.strip().upper()
    return bool(_CPT_PATTERN.match(cleaned) or _HCPCS_LEVEL_II_PATTERN.match(cleaned))


def is_valid_modifier_syntax(modifier: str) -> bool:
    return bool(_MODIFIER_PATTERN.match(modifier.strip().upper()))


@dataclass(frozen=True)
class CodeReferenceResult:
    known: bool
    description: str | None = None


class ProcedureCodeReferenceAdapter(Protocol):
    def lookup(self, code: str) -> CodeReferenceResult: ...


class NoOpProcedureCodeReferenceAdapter:
    """Default adapter: syntax-only validation, no CPT/HCPCS table
    lookup -- see icd10.py's `NoOpIcd10ReferenceAdapter` for the rationale."""

    def lookup(self, code: str) -> CodeReferenceResult:
        return CodeReferenceResult(known=False, description=None)
