"""End-to-end (in-process, fake object store, SQLite) of the event-driven
handoff: ingest -> document.received -> document_preparation worker ->
pages persisted -> document.prepared outbox event."""

import io

import pytest
from PIL import Image

from apps.ingestion_api.db.repository import (
    AuditRepository,
    DocumentRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from apps.ingestion_api.service import IngestionService
from packages.domain.common import TenantContext
from packages.domain.enums import DocumentStatus
from packages.events.bus import InMemoryEventBus
from packages.events.outbox import OutboxRelay
from packages.security.malware_scan import NoOpMalwareScanner
from workers.document_preparation.consumer import DocumentPreparationWorker


def _tiff_bytes(n_pages: int = 2) -> bytes:
    images = [Image.new("1", (200, 100), color=1) for _ in range(n_pages)]
    buf = io.BytesIO()
    images[0].save(
        buf, format="TIFF", compression="group4", save_all=True, append_images=images[1:]
    )
    return buf.getvalue()


@pytest.mark.asyncio
async def test_ingest_then_prepare_produces_pages_and_prepared_event(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    bus = InMemoryEventBus()

    with session_factory() as session:
        ingestion = IngestionService(
            object_store=fake_object_store,
            bucket="idp-documents",
            document_repository=DocumentRepository(session),
            audit_repository=AuditRepository(session),
            outbox_repository=SqlAlchemyOutboxRepository(session),
            malware_scanner=NoOpMalwareScanner(),
            pipeline_version="0.1.0",
            schema_version="1.0",
            max_upload_size_bytes=10 * 1024 * 1024,
        )
        result = await ingestion.ingest(
            "bundle.001", _tiff_bytes(3), TenantContext(tenant_id="tenant-1")
        )
        session.commit()
        document_id = result.document.document_id

    # relay the intake outbox event onto the bus, as OutboxRelay would in prod
    with session_factory() as session:
        outbox_repo = SqlAlchemyOutboxRepository(session)
        relay = OutboxRelay(repository=outbox_repo, event_bus=bus)
        bus._register_group("document.received", "document-preparation-worker")
        published = await relay.run_once()
        session.commit()
    assert published == 1

    worker = DocumentPreparationWorker(
        event_bus=bus,
        object_store=fake_object_store,
        bucket="idp-documents",
        session_factory=session_factory,
        pipeline_version="0.1.0",
    )
    envelope = await bus._queues[("document.received", "document-preparation-worker")].get()
    await worker.handle_one(envelope)

    with session_factory() as session:
        document = DocumentRepository(session).get(document_id)
        pages = PageRepository(session).list_for_document(document_id)

    assert document.status == DocumentStatus.PREPARED
    assert document.page_count == 3
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert all(p.original_object is not None for p in pages)
    assert all(p.extraction_object is not None for p in pages)

    with session_factory() as session:
        unpublished = await SqlAlchemyOutboxRepository(session).get_unpublished()
    assert any(r.topic == "document.prepared" for r in unpublished)
