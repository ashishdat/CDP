"""Validation results — field-level, never a single document-level score."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow
from packages.domain.enums import FieldCriticality, ValidationStatus


class ValidationResult(DomainModel):
    result_id: UUID = Field(default_factory=new_id)
    claim_id: UUID
    field_id: UUID | None = None
    field_name: str
    rule_name: str
    criticality: FieldCriticality
    status: ValidationStatus
    message: str | None = None
    evaluated_at: datetime = Field(default_factory=utcnow)
