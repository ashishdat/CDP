"""API-facing response models — deliberately separate from the internal
canonical `packages.domain.Document` so the wire contract can evolve
independently of the domain model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from packages.domain.document import Document


class DocumentResponse(BaseModel):
    document_id: UUID
    status: str
    detected_format: str
    sha256: str
    page_count: int
    source_filename: str
    received_at: datetime
    is_new_document: bool

    @classmethod
    def from_domain(cls, document: Document, is_new: bool) -> DocumentResponse:
        return cls(
            document_id=document.document_id,
            status=document.status.value,
            detected_format=document.detected_format.value,
            sha256=document.sha256,
            page_count=document.page_count,
            source_filename=document.source_filename,
            received_at=document.received_at,
            is_new_document=is_new,
        )
