"""Generated output artifacts (fixed-width, canonical JSON, X12)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, ObjectRef, new_id, utcnow
from packages.domain.enums import OutputFormatType


class OutputArtifact(DomainModel):
    artifact_id: UUID = Field(default_factory=new_id)
    claim_id: UUID
    document_id: UUID
    format: OutputFormatType
    spec_version: str
    object_ref: ObjectRef
    record_count: int = Field(ge=0)
    byte_length: int = Field(ge=0)
    sha256: str
    generated_at: datetime = Field(default_factory=utcnow)
    is_final: bool = False
