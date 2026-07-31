"""Immutable audit trail events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow
from packages.domain.enums import AuditEventType


class AuditEvent(DomainModel):
    """Append-only. No PHI values here — reference IDs and field names only."""

    audit_id: UUID = Field(default_factory=new_id)
    event_type: AuditEventType
    tenant_id: str
    correlation_id: UUID
    document_id: UUID | None = None
    claim_id: UUID | None = None
    actor: str  # "system:<worker_name>" or "user:<reviewer_id>"
    occurred_at: datetime = Field(default_factory=utcnow)
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)
