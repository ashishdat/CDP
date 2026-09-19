"""Narrow HITL route codes for claim decision (Track A/B/Package/Financial)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class HitlRoute(StrEnum):
    REGISTRATION_HITL = "REGISTRATION_HITL"
    FIELD_INK_HITL = "FIELD_INK_HITL"
    PACKAGE_HITL = "PACKAGE_HITL"
    FINANCIAL_RECONCILIATION_HITL = "FINANCIAL_RECONCILIATION_HITL"
    TRUE_STP = "TRUE_STP"


def route_claim_hitl(
    *,
    registration_ok: bool,
    package_complete: bool,
    unresolved_critical_fields: list[str],
    financial_disposition: str | None = None,
    llm_only_critical: bool = False,
) -> dict[str, Any]:
    """Route narrowly — do not send whole claim when one field needs review."""
    if not registration_ok:
        return {
            "route": HitlRoute.REGISTRATION_HITL.value,
            "fields": [],
            "reason": "REGISTRATION_UNTRUSTWORTHY",
        }
    if not package_complete:
        return {
            "route": HitlRoute.PACKAGE_HITL.value,
            "fields": [],
            "reason": "PACKAGE_INCOMPLETE",
        }
    fin = (financial_disposition or "").upper()
    if fin in {
        "LINE_SUM_UNCORROBORATED",
        "TOTAL_CONFLICT",
        "INCOMPLETE_SERVICE_LINES",
        "CHARGE_COLUMN_UNVERIFIED",
        "POS_BLEED_REJECTED",
        "EMPTY_FINANCIAL_INK",
    } or llm_only_critical:
        fields = [f for f in unresolved_critical_fields if "charge" in f.casefold()]
        return {
            "route": HitlRoute.FINANCIAL_RECONCILIATION_HITL.value,
            "fields": fields or unresolved_critical_fields[:1],
            "reason": fin or "LLM_ONLY_CRITICAL",
        }
    if unresolved_critical_fields:
        return {
            "route": HitlRoute.FIELD_INK_HITL.value,
            "fields": list(unresolved_critical_fields),
            "reason": "UNRESOLVED_CRITICAL_FIELDS",
        }
    return {
        "route": HitlRoute.TRUE_STP.value,
        "fields": [],
        "reason": "ALL_CRITICAL_ACCEPTED",
    }
