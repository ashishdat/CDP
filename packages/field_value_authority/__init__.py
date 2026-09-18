"""Field Value Authority — conflict equivalence and value selection.

Learning from Track-B residual HITL (Independent Samples-300 v11.1–v11.6):
most field HITL that is fixable without re-OCR is **OCR twin conflict**, not
missing ink. This package is the single authority for:

1. Are two OCR readings the same identity under known confusables?
2. Which display should win when they are twins / fragments?

The EvidenceReconciler remains the decision gate (thresholds, E2/E4/E6).
Authority only answers value-identity questions so rules stay testable and
reusable outside the reconciler call graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.candidate_reconciliation.reconciler import (
    _canonical_member_id,
    _member_id_is_shaped,
    _name_is_short_fragment,
    _name_is_strong_person,
    prefer_dob_without_january_dash_artifact,
    prefer_dob_without_separator_one,
    prefer_dob_year_confusable_digit,
    prefer_longer_name_prefix,
    prefer_member_id_without_confusable_insertion,
    prefer_name_canonical_token_order,
    prefer_name_with_optional_middle_initial,
    prefer_name_without_confusable_insertion,
    prefer_name_without_label_contamination,
    prefer_name_without_short_fragment,
    values_conflict_equivalent,
)


@dataclass(frozen=True)
class AuthorityDecision:
    """Result of resolving competing OCR values for one field."""

    selected_value: str | None
    equivalent: bool
    reason_code: str
    family: str


def field_family(field_name: str) -> str:
    name = (field_name or "").casefold()
    if name in {"patient_dob", "date_of_birth", "dob"} or "dob" in name:
        return "dob"
    if name in {"insured_id_number", "member_id", "subscriber_id"}:
        return "member_id"
    if name in {"patient_name", "insured_name"} or "name" in name:
        return "name"
    if any(token in name for token in ("charge", "amount", "paid")):
        return "charge"
    return "generic"


def are_equivalent(field_name: str, left: str, right: str) -> bool:
    """True when two OCR readings are not a genuine identity conflict."""
    return values_conflict_equivalent(field_name, left, right)


def prefer_authority(
    field_name: str, primary: str, competitors: list[str]
) -> AuthorityDecision:
    """Select the authoritative display among OCR twins / fragments."""
    family = field_family(field_name)
    competing = [v for v in competitors if (v or "").strip()]
    if family == "member_id":
        chosen = prefer_member_id_without_confusable_insertion(primary, competing)
        if chosen:
            compact = _canonical_member_id(chosen) if _member_id_is_shaped(chosen) else chosen
            return AuthorityDecision(compact, True, "MEMBER_ID_AUTHORITY", family)
        if _member_id_is_shaped(primary):
            return AuthorityDecision(
                _canonical_member_id(primary), False, "MEMBER_ID_COMPACT", family
            )
    if family == "name":
        for prefer_fn, code in (
            (prefer_name_without_label_contamination, "NAME_LABEL_AUTHORITY"),
            (prefer_name_without_short_fragment, "NAME_FRAGMENT_AUTHORITY"),
            (prefer_longer_name_prefix, "NAME_PREFIX_AUTHORITY"),
            (prefer_name_with_optional_middle_initial, "NAME_MI_AUTHORITY"),
            (prefer_name_canonical_token_order, "NAME_ORDER_AUTHORITY"),
            (prefer_name_without_confusable_insertion, "NAME_CONFUSABLE_AUTHORITY"),
        ):
            chosen = prefer_fn(primary, competing)
            if chosen:
                return AuthorityDecision(chosen, True, code, family)
    if family == "dob":
        for prefer_fn, code in (
            (prefer_dob_without_separator_one, "DOB_SEPARATOR_AUTHORITY"),
            (prefer_dob_without_january_dash_artifact, "DOB_JANUARY_AUTHORITY"),
            (prefer_dob_year_confusable_digit, "DOB_YEAR_CONFUSABLE_AUTHORITY"),
        ):
            chosen = prefer_fn(primary, competing)
            if chosen:
                return AuthorityDecision(chosen, True, code, family)
    return AuthorityDecision(primary, False, "PRIMARY_UNCHANGED", family)


def is_authoritative_shape(field_name: str, value: str) -> bool:
    family = field_family(field_name)
    if family == "member_id":
        return _member_id_is_shaped(value)
    if family == "name":
        return _name_is_strong_person(value) and not _name_is_short_fragment(value)
    return bool((value or "").strip())


__all__ = [
    "AuthorityDecision",
    "are_equivalent",
    "field_family",
    "is_authoritative_shape",
    "prefer_authority",
]
