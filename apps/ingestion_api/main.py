"""Ingestion API: streaming upload with size limits, magic-byte validation,
dedup, idempotent intake. See `apps/ingestion_api/batch_ingest.py` for the
batch-directory intake path used by ops/tests."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from apps.ingestion_api.db.repository import (
    AuditRepository,
    DocumentRepository,
    ExtractedFieldRepository,
    PollingOutboxRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from apps.ingestion_api.schemas import (
    DocumentResponse,
    DocumentResultResponse,
    ExtractedFieldResponse,
)
from apps.ingestion_api.service import (
    FileTooLargeError,
    IngestionService,
    MalwareDetectedError,
    UnsupportedFileTypeError,
)
from packages.domain.common import TenantContext
from packages.domain.enums import DocumentStatus
from packages.events.bus import AIOKafkaEventBus, InMemoryEventBus
from packages.events.outbox import OutboxRelay
from packages.observability import REGISTRY, configure_logging
from packages.observability.metrics import cache_hits_total, documents_received_total
from packages.security.malware_scan import NoOpMalwareScanner
from packages.production_runtime import assert_production_ready
from packages.settings import Settings, get_settings
from packages.storage.object_store import ObjectStore, ObjectStoreSettings

_state: dict[str, object] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("ingestion-api")
    settings = get_settings()
    assert_production_ready(settings)
    _state["settings"] = settings
    session_factory_override = app.dependency_overrides.get(get_session_factory)
    session_factory = (
        session_factory_override()
        if session_factory_override is not None
        else make_session_factory(settings.database_url)
    )
    _state["session_factory"] = session_factory
    object_store_override = app.dependency_overrides.get(get_object_store)
    if object_store_override is not None:
        object_store = object_store_override()
    else:
        object_store = ObjectStore(
            ObjectStoreSettings(
                endpoint_url=settings.object_store_endpoint,
                access_key=settings.object_store_access_key,
                secret_key=settings.object_store_secret_key,
                use_ssl=settings.object_store_use_ssl,
            )
        )
    try:
        object_store.ensure_bucket(settings.object_store_bucket)
    except Exception as exc:  # pragma: no cover - local/dev without MinIO
        if not settings.use_in_memory_bus:
            raise
        configure_logging("ingestion-api")
        logging.getLogger("ingestion-api").warning(
            "object store unavailable (%s); continuing because USE_IN_MEMORY_BUS=true",
            exc,
        )
    _state["object_store"] = object_store

    event_bus = (
        InMemoryEventBus()
        if settings.use_in_memory_bus
        else AIOKafkaEventBus(settings.kafka_bootstrap_servers)
    )
    relay = OutboxRelay(
        repository=PollingOutboxRepository(session_factory),
        event_bus=event_bus,
    )
    relay_task = asyncio.create_task(relay.run_forever())

    yield

    relay.stop()
    await relay_task
    await event_bus.close()
    _state.clear()


app = FastAPI(title="IDP Ingestion API", version="0.1.0", lifespan=lifespan)


def get_session_factory() -> sessionmaker[Session]:
    return _state["session_factory"]  # type: ignore[return-value]


def get_object_store() -> ObjectStore:
    return _state["object_store"]  # type: ignore[return-value]


def get_settings_dep() -> Settings:
    return _state["settings"]  # type: ignore[return-value]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if "session_factory" not in _state or "object_store" not in _state:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/documents", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    tenant_id: str = "default",
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    object_store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings_dep),
) -> DocumentResponse:
    data = await file.read()

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
                filename=file.filename or "unnamed",
                data=data,
                tenant=TenantContext(tenant_id=tenant_id),
            )
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        except FileTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except MalwareDetectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.commit()

    documents_received_total.labels(
        tenant_id=tenant_id, detected_format=result.document.detected_format.value
    ).inc()
    if not result.is_new_document:
        cache_hits_total.inc()

    return DocumentResponse.from_domain(result.document, is_new=result.is_new_document)


_PATIENT_FIELDS = ("patient_name", "patient_last", "patient_first")
_PAYER_FIELDS = ("payer_name", "insurance_plan_name", "insured_plan_name", "payer")


def _enrichment_for_documents(
    session: Session, doc_ids: list[UUID]
) -> dict[UUID, dict[str, object]]:
    """Resolve patient/payer display values and mean field confidence per document."""
    enrichment: dict[UUID, dict[str, object]] = {
        doc_id: {
            "patient_name": None,
            "payer_name": None,
            "average_confidence": None,
            "extracted_field_count": 0,
        }
        for doc_id in doc_ids
    }
    if not doc_ids:
        return enrichment

    from sqlalchemy import select

    from apps.ingestion_api.db.models import ExtractedFieldORM

    rows = session.execute(
        select(
            ExtractedFieldORM.document_id,
            ExtractedFieldORM.field_name,
            ExtractedFieldORM.raw_value,
            ExtractedFieldORM.normalized_value,
            ExtractedFieldORM.confidence,
        ).where(ExtractedFieldORM.document_id.in_(doc_ids))
    ).all()

    first_names: dict[UUID, str] = {}
    last_names: dict[UUID, str] = {}
    confidence_sums: dict[UUID, float] = {}
    confidence_counts: dict[UUID, int] = {}

    for doc_id, fname, raw_val, norm_val, confidence in rows:
        bucket = enrichment[doc_id]
        bucket["extracted_field_count"] = int(bucket["extracted_field_count"]) + 1
        confidence_sums[doc_id] = confidence_sums.get(doc_id, 0.0) + float(confidence)
        confidence_counts[doc_id] = confidence_counts.get(doc_id, 0) + 1

        val = norm_val or raw_val
        if not val:
            continue
        if fname == "patient_name":
            bucket["patient_name"] = val
        elif fname == "patient_last":
            last_names[doc_id] = val
        elif fname == "patient_first":
            first_names[doc_id] = val
        elif fname in _PAYER_FIELDS and bucket["payer_name"] is None:
            bucket["payer_name"] = val

    for doc_id in doc_ids:
        bucket = enrichment[doc_id]
        if bucket["patient_name"] is None:
            last = last_names.get(doc_id, "")
            first = first_names.get(doc_id, "")
            if last and first:
                bucket["patient_name"] = f"{last}, {first}"
            elif last or first:
                bucket["patient_name"] = last or first
        count = confidence_counts.get(doc_id, 0)
        if count:
            bucket["average_confidence"] = confidence_sums[doc_id] / count

    return enrichment


@app.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    tenant_id: str | None = None,
    limit: int = 1000,
    offset: int = 0,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> list[DocumentResponse]:
    with session_factory() as session:
        docs = DocumentRepository(session).list_all(tenant_id=tenant_id, limit=limit, offset=offset)
        enrichment = _enrichment_for_documents(session, [d.document_id for d in docs])
        return [
            DocumentResponse.from_domain(
                d,
                is_new=False,
                patient_name=enrichment[d.document_id]["patient_name"],  # type: ignore[arg-type]
                payer_name=enrichment[d.document_id]["payer_name"],  # type: ignore[arg-type]
                average_confidence=enrichment[d.document_id]["average_confidence"],  # type: ignore[arg-type]
                extracted_field_count=int(enrichment[d.document_id]["extracted_field_count"]),
            )
            for d in docs
        ]


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DocumentResponse:
    with session_factory() as session:
        document = DocumentRepository(session).get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        enrichment = _enrichment_for_documents(session, [document_id])[document_id]
    return DocumentResponse.from_domain(
        document,
        is_new=False,
        patient_name=enrichment["patient_name"],  # type: ignore[arg-type]
        payer_name=enrichment["payer_name"],  # type: ignore[arg-type]
        average_confidence=enrichment["average_confidence"],  # type: ignore[arg-type]
        extracted_field_count=int(enrichment["extracted_field_count"]),
    )


@app.get("/documents/{document_id}/results", response_model=DocumentResultResponse)
def get_document_results(
    document_id: UUID,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DocumentResultResponse:
    with session_factory() as session:
        document = DocumentRepository(session).get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        fields = ExtractedFieldRepository(session).list_for_document(document_id)
    terminal_statuses = {
        DocumentStatus.NEEDS_REVIEW,
        DocumentStatus.COMPLETED,
        DocumentStatus.OUTPUT_GENERATED,
        DocumentStatus.FAILED,
        DocumentStatus.QUARANTINED,
    }
    average_confidence = (
        sum(field.confidence for field in fields) / len(fields) if fields else None
    )
    return DocumentResultResponse(
        document=DocumentResponse.from_domain(
            document,
            is_new=False,
            average_confidence=average_confidence,
            extracted_field_count=len(fields),
        ),
        fields=[ExtractedFieldResponse.from_domain(field) for field in fields],
        field_count=len(fields),
        # The current vertical slice stops at VALIDATING after persisted OCR.
        processing_complete=bool(fields) or document.status in terminal_statuses,
    )
