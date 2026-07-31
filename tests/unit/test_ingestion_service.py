"""Ingestion: magic-byte validation, size limits, malware-scan interface,
and idempotent dedup keyed on sha256 + pipeline_version + schema_version."""

import io

import pytest
from PIL import Image

from apps.ingestion_api.db.repository import (
    AuditRepository,
    DocumentRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from apps.ingestion_api.service import (
    FileTooLargeError,
    IngestionService,
    MalwareDetectedError,
    UnsupportedFileTypeError,
)
from packages.domain.common import TenantContext
from packages.domain.enums import DocumentStatus
from packages.security.malware_scan import MalwareScanner, NoOpMalwareScanner, ScanResult


def _tiff_bytes() -> bytes:
    img = Image.new("1", (200, 100), color=1)
    buf = io.BytesIO()
    img.save(buf, format="TIFF", compression="group4")
    return buf.getvalue()


class DenyAllScanner:
    def scan(self, data: bytes) -> ScanResult:
        return ScanResult(is_clean=False, scanner_name="deny-all", details="test rejection")


def _make_service(fake_object_store, session, scanner: MalwareScanner | None = None):
    return IngestionService(
        object_store=fake_object_store,
        bucket="idp-documents",
        document_repository=DocumentRepository(session),
        audit_repository=AuditRepository(session),
        outbox_repository=SqlAlchemyOutboxRepository(session),
        malware_scanner=scanner or NoOpMalwareScanner(),
        pipeline_version="0.1.0",
        schema_version="1.0",
        max_upload_size_bytes=10 * 1024 * 1024,
    )


@pytest.fixture
def session():
    factory = make_session_factory("sqlite:///:memory:")
    with factory() as s:
        yield s


@pytest.mark.asyncio
async def test_ingest_accepts_a_valid_tiff_and_writes_outbox_event(fake_object_store, session):
    service = _make_service(fake_object_store, session)
    data = _tiff_bytes()

    result = await service.ingest(
        "claim.001", data, TenantContext(tenant_id="tenant-1")
    )
    session.commit()

    assert result.is_new_document is True
    assert result.document.status == DocumentStatus.RECEIVED
    assert result.outbox_record is not None
    assert result.outbox_record.envelope.payload["sha256"] == result.document.sha256


@pytest.mark.asyncio
async def test_ingest_rejects_unsupported_file_type(fake_object_store, session):
    service = _make_service(fake_object_store, session)
    with pytest.raises(UnsupportedFileTypeError):
        await service.ingest(
            "not-an-image.001", b"plain text, not an image", TenantContext(tenant_id="t1")
        )


@pytest.mark.asyncio
async def test_ingest_rejects_oversized_file(fake_object_store, session):
    service = IngestionService(
        object_store=fake_object_store,
        bucket="idp-documents",
        document_repository=DocumentRepository(session),
        audit_repository=AuditRepository(session),
        outbox_repository=SqlAlchemyOutboxRepository(session),
        malware_scanner=NoOpMalwareScanner(),
        pipeline_version="0.1.0",
        schema_version="1.0",
        max_upload_size_bytes=10,  # smaller than any real TIFF
    )
    with pytest.raises(FileTooLargeError):
        await service.ingest("claim.001", _tiff_bytes(), TenantContext(tenant_id="t1"))


@pytest.mark.asyncio
async def test_ingest_rejects_files_flagged_by_malware_scanner(fake_object_store, session):
    service = _make_service(fake_object_store, session, scanner=DenyAllScanner())
    with pytest.raises(MalwareDetectedError):
        await service.ingest("claim.001", _tiff_bytes(), TenantContext(tenant_id="t1"))


@pytest.mark.asyncio
async def test_reingesting_identical_bytes_is_idempotent(fake_object_store, session):
    service = _make_service(fake_object_store, session)
    data = _tiff_bytes()
    tenant = TenantContext(tenant_id="tenant-1")

    first = await service.ingest("claim.001", data, tenant)
    session.commit()
    second = await service.ingest("claim-resubmitted.001", data, tenant)
    session.commit()

    assert first.is_new_document is True
    assert second.is_new_document is False
    assert second.document.document_id == first.document.document_id
    assert second.outbox_record is None


@pytest.mark.asyncio
async def test_different_bytes_are_not_treated_as_duplicates(fake_object_store, session):
    service = _make_service(fake_object_store, session)
    tenant = TenantContext(tenant_id="tenant-1")

    first = await service.ingest("claim-a.001", _tiff_bytes(), tenant)
    session.commit()

    other_img = Image.new("1", (300, 150), color=1)
    buf = io.BytesIO()
    other_img.save(buf, format="TIFF", compression="group4")
    second = await service.ingest("claim-b.001", buf.getvalue(), tenant)
    session.commit()

    assert first.document.document_id != second.document.document_id
    assert second.is_new_document is True
