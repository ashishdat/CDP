"""Ingestion: validate, dedup, store, persist, outbox `document.received`.

This is the intake half of the "Document intake -> ... -> TIFF/PDF page
decoder" pipeline from the spec. The decode/preprocess half
(`workers.document_preparation`) is a separate consumer of
`document.received` — see `IngestionResult.is_new_document` for how a
caller distinguishes "just ingested, preparation will follow
asynchronously" from "exact duplicate of an already-processed document".
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.ingestion_api.db.repository import (
    AuditRepository,
    DocumentRepository,
    SqlAlchemyOutboxRepository,
)
from packages.domain.audit import AuditEvent
from packages.domain.common import TenantContext
from packages.domain.document import Document
from packages.domain.enums import AuditEventType, DocumentStatus, SourceFormat
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.security.malware_scan import MalwareScanner
from packages.storage.file_types import detect_file_type
from packages.storage.hashing import sha256_bytes
from packages.storage.object_store import ObjectStore, content_addressed_key


class UnsupportedFileTypeError(ValueError):
    pass


class FileTooLargeError(ValueError):
    pass


class MalwareDetectedError(ValueError):
    pass


@dataclass
class IngestionResult:
    document: Document
    is_new_document: bool
    outbox_record: OutboxRecord | None


class IngestionService:
    def __init__(
        self,
        object_store: ObjectStore,
        bucket: str,
        document_repository: DocumentRepository,
        audit_repository: AuditRepository,
        outbox_repository: SqlAlchemyOutboxRepository,
        malware_scanner: MalwareScanner,
        pipeline_version: str,
        schema_version: str,
        max_upload_size_bytes: int,
    ) -> None:
        self._object_store = object_store
        self._bucket = bucket
        self._documents = document_repository
        self._audit = audit_repository
        self._outbox = outbox_repository
        self._scanner = malware_scanner
        self._pipeline_version = pipeline_version
        self._schema_version = schema_version
        self._max_upload_size_bytes = max_upload_size_bytes

    async def ingest(
        self, filename: str, data: bytes, tenant: TenantContext
    ) -> IngestionResult:
        if len(data) > self._max_upload_size_bytes:
            raise FileTooLargeError(
                f"{filename}: {len(data)} bytes exceeds limit of "
                f"{self._max_upload_size_bytes} bytes"
            )

        file_type = detect_file_type(data)
        if not file_type.is_supported:
            raise UnsupportedFileTypeError(
                f"{filename}: unrecognized magic bytes, not TIFF/PDF/PNG/JPEG"
            )

        scan_result = self._scanner.scan(data)
        if not scan_result.is_clean:
            raise MalwareDetectedError(f"{filename}: {scan_result.details}")

        digest = sha256_bytes(data)

        existing = self._documents.find_by_idempotency_key(
            digest, self._pipeline_version, self._schema_version
        )
        if existing is not None:
            self._audit.add(
                AuditEvent(
                    event_type=AuditEventType.DUPLICATE_DETECTED,
                    tenant_id=tenant.tenant_id,
                    correlation_id=tenant.correlation_id,
                    document_id=existing.document_id,
                    actor="system:ingestion_api",
                    details={"sha256": digest, "source_filename": filename},
                )
            )
            return IngestionResult(document=existing, is_new_document=False, outbox_record=None)

        key = content_addressed_key(digest, filename)
        object_ref = self._object_store.put_immutable(
            self._bucket, key, data, content_type=_content_type_for(file_type.format)
        )

        document = Document(
            tenant_id=tenant.tenant_id,
            correlation_id=tenant.correlation_id,
            source_filename=filename,
            detected_format=file_type.format,
            sha256=digest,
            status=DocumentStatus.RECEIVED,
            original_object=object_ref,
            pipeline_version=self._pipeline_version,
            schema_version=self._schema_version,
        )
        self._documents.add(document)

        self._audit.add(
            AuditEvent(
                event_type=AuditEventType.DOCUMENT_RECEIVED,
                tenant_id=tenant.tenant_id,
                correlation_id=tenant.correlation_id,
                document_id=document.document_id,
                actor="system:ingestion_api",
                details={"sha256": digest, "source_filename": filename},
            )
        )

        envelope = EventEnvelope(
            event_type=Topic.DOCUMENT_RECEIVED.value,
            correlation_id=tenant.correlation_id,
            document_id=document.document_id,
            pipeline_version=self._pipeline_version,
            payload={
                "document_id": str(document.document_id),
                "tenant_id": tenant.tenant_id,
                "source_object": object_ref.model_dump(mode="json"),
                "detected_format": file_type.format.value,
                "sha256": digest,
            },
        )
        outbox_record = OutboxRecord(
            topic=Topic.DOCUMENT_RECEIVED.value,
            envelope=envelope,
            partition_key=str(document.document_id),
        )
        await self._outbox.add(outbox_record)

        return IngestionResult(
            document=document, is_new_document=True, outbox_record=outbox_record
        )


def _content_type_for(fmt: SourceFormat) -> str:
    return {
        SourceFormat.TIFF: "image/tiff",
        SourceFormat.PDF: "application/pdf",
        SourceFormat.PNG: "image/png",
        SourceFormat.JPEG: "image/jpeg",
    }.get(fmt, "application/octet-stream")
