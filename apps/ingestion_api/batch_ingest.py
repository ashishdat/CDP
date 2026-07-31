"""Batch-directory ingestion: walk a directory, ingest every file whose
magic bytes we recognize (TIFF/PDF/PNG/JPEG), skip everything else. Used
for ops backfills and for exercising the ingestion pipeline against the
supplied sample dataset in integration tests.

Usage:
    python -m apps.ingestion_api.batch_ingest <directory> [--tenant-id ID]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from apps.ingestion_api.db.repository import (
    AuditRepository,
    DocumentRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from apps.ingestion_api.service import IngestionService, UnsupportedFileTypeError
from packages.domain.common import TenantContext
from packages.security.malware_scan import NoOpMalwareScanner
from packages.settings import get_settings
from packages.storage.object_store import ObjectStore, ObjectStoreSettings

logger = logging.getLogger(__name__)


async def ingest_directory(
    directory: Path, tenant_id: str = "default", database_url: str | None = None
) -> list[str]:
    settings = get_settings()
    session_factory = make_session_factory(database_url or settings.database_url)
    object_store = ObjectStore(
        ObjectStoreSettings(
            endpoint_url=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            use_ssl=settings.object_store_use_ssl,
        )
    )
    object_store.ensure_bucket(settings.object_store_bucket)

    results: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        with session_factory() as session:
            service = IngestionService(
                object_store=object_store,
                bucket=settings.object_store_bucket,
                document_repository=DocumentRepository(session),
                audit_repository=AuditRepository(session),
                outbox_repository=SqlAlchemyOutboxRepository(session),
                malware_scanner=NoOpMalwareScanner(),
                pipeline_version=settings.pipeline_version,
                schema_version=settings.schema_version,
                max_upload_size_bytes=settings.max_upload_size_bytes,
            )
            try:
                result = await service.ingest(
                    filename=path.name,
                    data=data,
                    tenant=TenantContext(tenant_id=tenant_id),
                )
            except UnsupportedFileTypeError:
                logger.info("skipping unsupported file: %s", path.name)
                continue
            session.commit()
        results.append(str(result.document.document_id))
        logger.info(
            "ingested %s -> document_id=%s new=%s",
            path.name,
            result.document.document_id,
            result.is_new_document,
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tenant-id", default="default")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ingest_directory(args.directory, args.tenant_id))


if __name__ == "__main__":
    main()
