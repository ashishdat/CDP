"""Fail-closed HITL optimization using authorized evidence only."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class HitlDisposition(StrEnum):
    ALREADY_AUTOMATED = "ALREADY_AUTOMATED"
    PROMOTED_REFERENCE_VERIFIED = "PROMOTED_REFERENCE_VERIFIED"
    PROMOTED_ACTIVE_ROUTE = "PROMOTED_ACTIVE_ROUTE"
    BLOCKED_REFERENCE_REQUIRED = "BLOCKED_REFERENCE_REQUIRED"
    BLOCKED_HOLDOUT_REQUIRED = "BLOCKED_HOLDOUT_REQUIRED"
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"
    BLOCKED_CONTRADICTION = "BLOCKED_CONTRADICTION"


@dataclass(frozen=True)
class HitlDecision:
    disposition: HitlDisposition
    automatically_acceptable: bool
    reason: str


def identity_key(prediction: dict[str, Any]) -> str:
    identity = prediction["field_identity"]
    return "|".join(str(identity.get(key) or "") for key in (
        "document_id", "page_number", "document_family", "service_line_number",
        "semantic_field",
    ))


def route_key(prediction: dict[str, Any]) -> str:
    identity = prediction["field_identity"]
    return f"{identity.get('document_family')}|{identity.get('semantic_field')}"


def decide(
    prediction: dict[str, Any],
    policy: dict[str, Any],
    *,
    reference_decisions: dict[str, str],
    active_routes: set[str],
) -> HitlDecision:
    if not prediction.get("review_required", False):
        return HitlDecision(HitlDisposition.ALREADY_AUTOMATED, True, "existing automatic disposition")
    validations = set(prediction.get("validation_results") or [])
    reference = reference_decisions.get(identity_key(prediction))
    if reference in set(policy["reference_promotion"]["reject_decisions"]):
        return HitlDecision(HitlDisposition.BLOCKED_CONTRADICTION, False, reference)
    if reference == policy["reference_promotion"]["required_decision"]:
        return HitlDecision(
            HitlDisposition.PROMOTED_REFERENCE_VERIFIED,
            True,
            "authorized multi-attribute reference verification",
        )
    reason = (prediction.get("provenance") or {}).get("reason")
    field = prediction["field_identity"].get("semantic_field")
    if reason in policy["reference_required_reasons"] or field in policy["critical_identity_fields"]:
        return HitlDecision(
            HitlDisposition.BLOCKED_REFERENCE_REQUIRED,
            False,
            "authorized reference decision unavailable",
        )
    route = route_key(prediction)
    if route not in active_routes:
        return HitlDecision(
            HitlDisposition.BLOCKED_HOLDOUT_REQUIRED,
            False,
            f"field-family route is not ACTIVE: {route}",
        )
    required = set(policy["route_promotion"]["required_validation_results"])
    forbidden = set(policy["route_promotion"]["forbidden_validation_results"])
    if required.issubset(validations) and not validations.intersection(forbidden):
        return HitlDecision(
            HitlDisposition.PROMOTED_ACTIVE_ROUTE,
            True,
            "active field-family route with required independent validation",
        )
    return HitlDecision(
        HitlDisposition.BLOCKED_INSUFFICIENT_EVIDENCE,
        False,
        "active route lacks required validation evidence",
    )
