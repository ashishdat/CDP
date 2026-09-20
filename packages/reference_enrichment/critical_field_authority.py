"""Governed critical-field authority from authorized member reference.

OCR AUTO is never weakened. Reference fills unresolved identity fields only
when an exact verified member ID joins an operator-authorized index row.
``total_charge`` is never filled from reference — Box 28 ↔ Box 24F only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

CRITICAL_FIELDS = {
    "patient_name",
    "insured_name",
    "patient_dob",
    "insured_id_number",
    "total_charge",
}

# Fields eligible for authorized-reference AUTO after OCR fails closed.
REFERENCE_ELIGIBLE_FIELDS = frozenset({"patient_name", "insured_name", "patient_dob"})


@dataclass(frozen=True)
class AuthorityResult:
    disposition: str  # AUTO_ACCEPTED | ESCALATE
    value: str | None
    evidence_type: str | None
    reason: str
    metadata: Mapping[str, object]


def resolve_critical_field(
    *,
    field: str,
    ocr_value: str | None,
    ocr_auto: bool,
    verified_member_id: str | None,
    reference: Mapping[str, object] | None,
    document_date: str | None,
) -> AuthorityResult:
    """Resolve one critical field. Never synthesizes charge totals from reference."""
    # Preserve existing OCR AUTO; this function must never weaken it.
    if ocr_auto and ocr_value:
        return AuthorityResult(
            "AUTO_ACCEPTED",
            ocr_value,
            "INDEPENDENT_OCR",
            "OCR_AUTHORITY",
            {},
        )

    # total_charge stays Box 28 ↔ Box 24F strict — never reference-filled.
    if field == "total_charge":
        return AuthorityResult(
            "ESCALATE",
            None,
            None,
            "REFERENCE_FORBIDDEN_FOR_TOTAL_CHARGE",
            {},
        )

    if field not in REFERENCE_ELIGIBLE_FIELDS and field in CRITICAL_FIELDS:
        # insured_id_number is the join key, not a reference fill target here.
        return AuthorityResult(
            "ESCALATE",
            None,
            None,
            "REFERENCE_NOT_APPLICABLE_FOR_FIELD",
            {"field": field},
        )

    # Never use reference data without a verified exact identifier.
    if not verified_member_id or not reference:
        return AuthorityResult("ESCALATE", None, None, "NO_AUTHORIZED_REFERENCE", {})
    if str(reference.get("member_id") or "").strip() != verified_member_id:
        return AuthorityResult("ESCALATE", None, None, "REFERENCE_ID_MISMATCH", {})
    if not bool(reference.get("authorized")):
        return AuthorityResult("ESCALATE", None, None, "REFERENCE_NOT_AUTHORIZED", {})
    if not bool(reference.get("identity_verified")):
        return AuthorityResult(
            "ESCALATE", None, None, "REFERENCE_IDENTITY_NOT_VERIFIED", {}
        )
    if (
        document_date
        and reference.get("effective_from")
        and str(reference["effective_from"]) > document_date
    ):
        return AuthorityResult("ESCALATE", None, None, "REFERENCE_NOT_EFFECTIVE", {})

    value = str(reference.get(field) or "").strip()
    if not value:
        return AuthorityResult("ESCALATE", None, None, "REFERENCE_FIELD_MISSING", {})

    return AuthorityResult(
        "AUTO_ACCEPTED",
        value,
        "AUTHORIZED_REFERENCE",
        "EXACT_ID_AUTHORIZED_REFERENCE",
        {
            "member_id": verified_member_id,
            "reference_version": reference.get("version"),
            "effective_from": reference.get("effective_from"),
            "field": field,
            "source": reference.get("source") or "AUTHORIZED_MEMBER_INDEX",
        },
    )


def lookup_authorized_reference(
    member_id: object,
    *,
    index: dict[str, dict] | None = None,
) -> dict[str, object] | None:
    """Return a reference row with ``member_id`` injected, or None if abstaining."""
    from packages.reference_enrichment.authorized_member_join import (
        load_authorized_member_index,
    )

    mid = str(member_id or "").strip()
    if not mid:
        return None
    table = index if index is not None else load_authorized_member_index()
    if not table:
        return None
    row = table.get(mid)
    if not isinstance(row, dict):
        digits = "".join(ch for ch in mid if ch.isdigit())
        row = table.get(digits) if digits else None
    if not isinstance(row, dict):
        return None
    out = dict(row)
    out["member_id"] = mid
    return out
