"""Safety policy for candidates verified by authorized runtime providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceEvidence:
    member_id_exact: bool = False
    dob_exact: bool = False
    patient_name_score: float = 0.0
    address_score: float = 0.0
    provider_npi_exact: bool = False
    provider_name_score: float = 0.0
    payer_relationship_exact: bool = False


def critical_reference_acceptance(evidence: ReferenceEvidence) -> bool:
    """Name-only fuzzy evidence is never sufficient for critical acceptance."""
    member_identity = (
        evidence.member_id_exact
        and evidence.dob_exact
        and evidence.patient_name_score >= 0.90
    )
    provider_identity = (
        evidence.provider_npi_exact and evidence.provider_name_score >= 0.85
    )
    return member_identity or provider_identity
