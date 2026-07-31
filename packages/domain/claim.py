"""Canonical claim aggregate — the output of extraction + validation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow
from packages.domain.enums import ClaimFormType, DocumentStatus, ValidationStatus
from packages.domain.extraction import ExtractedField


class PersonName(DomainModel):
    first: str | None = None
    middle: str | None = None
    last: str | None = None
    suffix: str | None = None


class Address(DomainModel):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class CodeAmountPair(DomainModel):
    code: str
    amount: Decimal | None = None


class CodeDatePair(DomainModel):
    code: str
    occurrence_date: date | None = Field(default=None, alias="date")


class PayerMember(DomainModel):
    payer_name: str | None = None
    payer_id: str | None = None
    member_id: str | None = None
    group_number: str | None = None
    relationship: str | None = None


class ServiceLine(DomainModel):
    line_id: UUID = Field(default_factory=new_id)
    line_number: int = Field(ge=1)
    service_date_from: date | None = None
    service_date_to: date | None = None
    place_of_service: str | None = None
    procedure_code: str | None = None
    modifiers: list[str] = Field(default_factory=list)
    diagnosis_pointers: list[str] = Field(default_factory=list)
    units: Decimal | None = None
    charge_amount: Decimal | None = None
    revenue_code: str | None = None
    hcpcs_code: str | None = None
    rendering_provider_npi: str | None = None
    non_covered_charge_amount: Decimal | None = None
    fields: list[ExtractedField] = Field(default_factory=list)


class Claim(DomainModel):
    claim_id: UUID = Field(default_factory=new_id)
    document_id: UUID
    tenant_id: str
    correlation_id: UUID
    form_type: ClaimFormType
    schema_version: str
    template_version: str | None = None

    patient_name: str | None = None
    patient_name_components: PersonName | None = None
    patient_dob: date | None = None
    patient_sex: str | None = None
    patient_address: Address | None = None
    insured_name_components: PersonName | None = None
    insured_address: Address | None = None
    subscriber_id: str | None = None
    insured_relationship: str | None = None
    provider_npi: str | None = None
    provider_tax_id: str | None = None
    payer_name: str | None = None
    patient_account_number: str | None = None
    amount_paid: Decimal | None = None
    billing_provider_name: str | None = None
    billing_provider_address: Address | None = None
    billing_provider_npi: str | None = None
    billing_provider_identifier: str | None = None

    diagnosis_codes: list[str] = Field(default_factory=list)
    diagnosis_codes_by_position: dict[str, str] = Field(default_factory=dict)
    service_lines: list[ServiceLine] = Field(default_factory=list)
    total_charge_amount: Decimal | None = None

    # UB-04 repeating and institutional fields. Existing composite fields
    # above remain for schema-version compatibility.
    statement_period_from: date | None = None
    statement_period_to: date | None = None
    value_codes: list[CodeAmountPair] = Field(default_factory=list)
    occurrence_codes: list[CodeDatePair] = Field(default_factory=list)
    condition_codes: list[str] = Field(default_factory=list)
    principal_diagnosis: str | None = None
    additional_diagnoses: list[str] = Field(default_factory=list)
    attending_provider_name: PersonName | None = None
    attending_provider_npi: str | None = None
    payer_members: list[PayerMember] = Field(default_factory=list)

    header_fields: list[ExtractedField] = Field(default_factory=list)

    status: DocumentStatus = DocumentStatus.EXTRACTING
    validation_status: ValidationStatus = ValidationStatus.PENDING

    version: int = Field(default=1, ge=1)  # optimistic-locking version
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def all_fields(self) -> list[ExtractedField]:
        fields = list(self.header_fields)
        for line in self.service_lines:
            fields.extend(line.fields)
        return fields
