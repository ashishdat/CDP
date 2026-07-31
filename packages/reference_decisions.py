"""Multi-attribute decisions for authorized reference connectors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReferenceDecision(StrEnum):
    REFERENCE_VERIFIED = "REFERENCE_VERIFIED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    REFERENCE_CONTRADICTION = "REFERENCE_CONTRADICTION"


@dataclass(frozen=True)
class MemberMatchEvidence:
    member_id_exact: bool
    dob_exact: bool
    normalized_name_similarity: float
    address_consistent: bool | None
    service_date_eligible: bool | None = None


@dataclass(frozen=True)
class ProviderMatchEvidence:
    npi_exact: bool
    normalized_name_similarity: float
    address_consistent: bool | None


def decide_member(evidence: MemberMatchEvidence, *, name_threshold: float = 0.92) -> ReferenceDecision:
    if evidence.address_consistent is False or evidence.service_date_eligible is False:
        return ReferenceDecision.REFERENCE_CONTRADICTION
    if (
        evidence.member_id_exact
        and evidence.dob_exact
        and evidence.normalized_name_similarity >= name_threshold
    ):
        return ReferenceDecision.REFERENCE_VERIFIED
    return ReferenceDecision.HUMAN_REVIEW_REQUIRED


def decide_provider(evidence: ProviderMatchEvidence, *, name_threshold: float = 0.90) -> ReferenceDecision:
    if evidence.address_consistent is False:
        return ReferenceDecision.REFERENCE_CONTRADICTION
    if evidence.npi_exact and evidence.normalized_name_similarity >= name_threshold:
        return ReferenceDecision.REFERENCE_VERIFIED
    return ReferenceDecision.HUMAN_REVIEW_REQUIRED
