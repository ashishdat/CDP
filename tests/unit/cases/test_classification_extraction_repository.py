"""Persistence for the two tables introduced to support real OCR wiring:
`PageClassificationORM` (workers.page_detection results) and
`ExtractedFieldORM` (workers.standard_form_extraction results). Neither had
an ORM home before -- `PageClassification`/`ExtractedField` were
domain-only models with no repository."""

from uuid import uuid4

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    PageClassificationRepository,
    PageRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.domain.classification import PageClassification
from packages.domain.common import BoundingBox, ObjectRef
from packages.domain.document import Document
from packages.domain.enums import (
    ClassificationMethod,
    CompressionType,
    DocumentStatus,
    ExtractionMethod,
    PageRole,
    SourceFormat,
    ValidationStatus,
)
from packages.domain.extraction import ExtractedField


def _document() -> Document:
    return Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="a" * 64,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/x.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
    )


def _bbox() -> BoundingBox:
    return BoundingBox(x0=10, y0=10, x1=100, y1=40, image_width=1712, image_height=2214)


def test_page_classification_round_trips():
    session_factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    page_id = uuid4()

    with session_factory() as session:
        DocumentRepository(session).add(document)
        session.commit()

    classification = PageClassification(
        page_id=page_id,
        document_id=document.document_id,
        role=PageRole.CMS1500_CLAIM_PAGE,
        confidence=0.92,
        method=ClassificationMethod.TRUSTED_ANCHOR_SKIP,
        template_id="cms1500",
        template_version="02-12",
        reason_codes=["cms1500_anchors_matched"],
        needs_review=False,
    )

    with session_factory() as session:
        PageClassificationRepository(session).add_all([classification])
        session.commit()

    with session_factory() as session:
        rows = PageClassificationRepository(session).list_for_document(document.document_id)

    assert len(rows) == 1
    assert rows[0].role == PageRole.CMS1500_CLAIM_PAGE
    assert rows[0].method == ClassificationMethod.TRUSTED_ANCHOR_SKIP
    assert rows[0].confidence == 0.92
    assert rows[0].template_id == "cms1500"
    assert rows[0].reason_codes == ["cms1500_anchors_matched"]


def test_extracted_field_round_trips_with_service_line_number():
    session_factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    with session_factory() as session:
        DocumentRepository(session).add(document)
        session.commit()

    header_field = ExtractedField(
        field_name="patient_name",
        raw_value="JANE DOE",
        normalized_value="JANE DOE",
        confidence=0.85,
        page_number=1,
        bounding_box=_bbox(),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        validation_status=ValidationStatus.PENDING,
    )
    service_line_field = ExtractedField(
        field_name="procedure_code",
        raw_value="99213",
        normalized_value="99213",
        confidence=0.85,
        page_number=1,
        bounding_box=_bbox(),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        validation_status=ValidationStatus.PENDING,
    )

    with session_factory() as session:
        repo = ExtractedFieldRepository(session)
        repo.add_all(document.document_id, [header_field], service_line_number=None)
        repo.add_all(document.document_id, [service_line_field], service_line_number=1)
        session.commit()

    with session_factory() as session:
        rows = ExtractedFieldRepository(session).list_for_document(document.document_id)

    assert len(rows) == 2
    by_name = {r.field_name: r for r in rows}
    assert by_name["patient_name"].raw_value == "JANE DOE"
    assert by_name["procedure_code"].normalized_value == "99213"


def test_page_repository_update_roles():
    from packages.domain.document import Page

    session_factory = make_session_factory("sqlite:///:memory:")
    document = _document()

    real_page = Page(
        document_id=document.document_id,
        page_number=1,
        width_px=1712,
        height_px=2214,
        compression=CompressionType.UNCOMPRESSED,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/p1.png"),
    )

    with session_factory() as session:
        DocumentRepository(session).add(document)
        PageRepository(session).add_all([real_page])
        session.commit()

    with session_factory() as session:
        PageRepository(session).update_roles({real_page.page_id: PageRole.ATTACHMENT.value})
        session.commit()

    with session_factory() as session:
        pages = PageRepository(session).list_for_document(document.document_id)

    assert pages[0].role == PageRole.ATTACHMENT.value
    assert document.status == DocumentStatus.RECEIVED  # unrelated field untouched by this call
