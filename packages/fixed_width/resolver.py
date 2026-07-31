"""Resolves a field spec's `source_field` (a dotted attribute path, e.g.
`"provider_tax_id"` or `"billing_provider.npi"`) against a canonical
domain object into the string `render_field` expects.

Handles simple attribute chains only (no list indexing) -- sufficient for
header-level records (NSF AA0/BA0/BA1/CA0, UB92 01/10/20, ...). Service-
line-level records (NSF FA0, UB92 60) are populated by the output-
generation worker iterating `claim.service_lines` directly rather than
through this resolver; extending it to `service_lines[0].charge_amount`-
style paths is a natural follow-up once that worker lands (Phase 3/4), not
a blocker for the header-record writer/validator this module supports today.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


class FieldResolutionError(LookupError):
    pass


def resolve_source_field(obj: Any, path: str) -> str:
    current = obj
    for part in path.split("."):
        if current is None:
            return ""
        try:
            current = getattr(current, part)
        except AttributeError as exc:
            raise FieldResolutionError(f"no attribute '{part}' on path '{path}'") from exc

    if current is None:
        return ""
    if isinstance(current, date):
        return current.strftime("%Y%m%d")
    if isinstance(current, Decimal):
        return str(int(current * 100))  # implied 2-decimal cents, the common case here
    return str(current)


def resolve_field_values(obj: Any, source_fields: dict[str, str | None]) -> dict[str, str]:
    """`source_fields` maps field_name -> dotted path (or None to skip,
    leaving the spec's `default` in place)."""
    values: dict[str, str] = {}
    for field_name, path in source_fields.items():
        if path is None:
            continue
        values[field_name] = resolve_source_field(obj, path)
    return values
