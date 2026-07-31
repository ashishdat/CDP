"""Runtime interfaces for approved, independent reference data sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MemberReference:
    member_id: str
    name: str
    date_of_birth: str | None = None


@dataclass(frozen=True)
class ProviderReference:
    npi: str
    name: str


@dataclass(frozen=True)
class AddressReference:
    address_id: str
    normalized_address: str


@dataclass(frozen=True)
class AddressVerificationResult:
    verified: bool
    normalized_address: str | None
    provider_name: str
    provider_version: str
    matched_attributes: tuple[str, ...]
    contradictions: tuple[str, ...]
    confidence: float
    reference_record_id: str | None
    reason_codes: tuple[str, ...]
    authorized: bool = False
    automatic_acceptance_permitted: bool = False


@dataclass(frozen=True)
class MedicalCodeReference:
    code: str
    code_system: str
    active: bool


class MemberReferenceProvider(Protocol):
    def find_member(self, member_id: str) -> MemberReference | None: ...


class ProviderReferenceProvider(Protocol):
    def find_provider(self, npi: str) -> ProviderReference | None: ...


class AddressReferenceProvider(Protocol):
    def normalize_address(self, value: str) -> AddressReference | None: ...

    def verify_address(
        self,
        *,
        po_box: str | None,
        postal_code: str | None,
        city: str | None,
        state: str | None,
    ) -> AddressVerificationResult: ...


class UnconfiguredAddressReferenceProvider:
    provider_name = "unconfigured"
    provider_version = "0"

    def normalize_address(self, value: str) -> AddressReference | None:
        return None

    def verify_address(
        self,
        *,
        po_box: str | None,
        postal_code: str | None,
        city: str | None,
        state: str | None,
    ) -> AddressVerificationResult:
        return AddressVerificationResult(
            verified=False,
            normalized_address=None,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            matched_attributes=(),
            contradictions=(),
            confidence=0.0,
            reference_record_id=None,
            reason_codes=(
                "AWAITING_AUTHORIZED_DATASET",
                "ADDRESS_REFERENCE_REQUIRED",
                "HUMAN_REVIEW_REQUIRED",
            ),
        )


def address_can_auto_accept(result: AddressVerificationResult) -> bool:
    required = {"po_box", "postal_code", "city", "state"}
    return (
        result.authorized
        and result.verified
        and result.automatic_acceptance_permitted
        and required.issubset(result.matched_attributes)
        and not result.contradictions
        and result.normalized_address is not None
    )


class MedicalCodeReferenceProvider(Protocol):
    def find_code(self, code: str, code_system: str) -> MedicalCodeReference | None: ...
