"""Hybrid model router decision record."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow
from packages.domain.enums import ExtractionMethod


class ModelDecision(DomainModel):
    decision_id: UUID = Field(default_factory=new_id)
    claim_id: UUID | None = None
    field_name: str | None = None
    selected_route: ExtractionMethod
    reason_codes: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = Field(ge=0, default=0.0)
    model_name: str | None = None
    model_version: str | None = None
    escalation_count: int = Field(ge=0, default=0)
    decided_at: datetime = Field(default_factory=utcnow)
