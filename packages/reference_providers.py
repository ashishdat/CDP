"""Production reference-provider contracts; evaluation truth is never an implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MemberReference:
    member_id: str
    name: str
    dob: str
    address: str | None
    source_system: str
    record_version: str


@dataclass(frozen=True)
class ProviderReference:
    npi: str
    name: str
    address: str | None
    source_system: str
    record_version: str


class MemberReferenceProvider(Protocol):
    def lookup_member(self, member_id: str) -> list[MemberReference]: ...


class ProviderDirectory(Protocol):
    def lookup_npi(self, npi: str) -> ProviderReference | None: ...


class EligibilityProvider(Protocol):
    def verify_enrollment(self, member_id: str, service_date: str) -> bool | None: ...


def member_reference_passes(
    candidate: MemberReference,
    *,
    member_id: str,
    dob: str,
    name_similarity: float,
    minimum_name_similarity: float = 0.92,
    contradictory_evidence: bool = False,
) -> bool:
    return (
        candidate.member_id == member_id
        and candidate.dob == dob
        and name_similarity >= minimum_name_similarity
        and not contradictory_evidence
    )
