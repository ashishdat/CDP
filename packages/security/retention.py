"""Configurable retention + deletion workflow. Defined against a small
repository protocol (not `apps.ingestion_api.db` directly) so the policy
logic is unit-testable without a database; `apps/ingestion_api/db/
repository.py::DocumentRepository` implements the protocol for real use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from packages.domain.audit import AuditEvent
from packages.domain.document import Document
from packages.domain.enums import AuditEventType


@dataclass(frozen=True)
class RetentionPolicy:
    tenant_id: str
    retention_days: int


class DocumentRetentionRepository(Protocol):
    def find_received_before(self, tenant_id: str, cutoff: datetime) -> list[Document]: ...
    def delete(self, document_id: UUID) -> None: ...


class ObjectDeleter(Protocol):
    def delete_object(self, bucket: str, key: str) -> None: ...


class RetentionService:
    def __init__(
        self, repository: DocumentRetentionRepository, object_store: ObjectDeleter
    ) -> None:
        self._repository = repository
        self._object_store = object_store

    def find_expired_documents(self, policy: RetentionPolicy, as_of: datetime) -> list[Document]:
        cutoff = as_of.replace(microsecond=0) - timedelta(days=policy.retention_days)
        return self._repository.find_received_before(policy.tenant_id, cutoff)

    def delete_document(self, document: Document, actor: str) -> AuditEvent:
        self._object_store.delete_object(
            document.original_object.bucket, document.original_object.key
        )
        self._repository.delete(document.document_id)
        return AuditEvent(
            event_type=AuditEventType.RECORD_DELETED,
            tenant_id=document.tenant_id,
            correlation_id=document.correlation_id,
            document_id=document.document_id,
            actor=actor,
            details={"sha256": document.sha256, "reason": "retention_policy_expired"},
        )

    def run_retention_sweep(
        self, policy: RetentionPolicy, as_of: datetime, actor: str = "system:retention_sweep"
    ) -> list[AuditEvent]:
        expired = self.find_expired_documents(policy, as_of)
        return [self.delete_document(doc, actor) for doc in expired]
