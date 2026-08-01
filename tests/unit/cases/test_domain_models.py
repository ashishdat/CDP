"""Smoke tests for the canonical domain model."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.domain.claim import Claim, ServiceLine
from packages.domain.common import BoundingBox, ObjectRef
from packages.domain.document import Document
from packages.domain.enums import (
    ClaimFormType,
    CompressionType,
    ExtractionMethod,
    SourceFormat,
)
from packages.domain.extraction import ExtractedField


def _object_ref() -> ObjectRef:
    return ObjectRef(bucket="idp-documents", key="documents/ab/cd/hash_file.tiff")


def test_document_idempotency_key_combines_hash_pipeline_and_schema_version():
    doc = Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="a" * 64,
        original_object=_object_ref(),
        pipeline_version="0.1.0",
        schema_version="1.0",
    )
    assert doc.idempotency_key == f"{'a' * 64}:0.1.0:1.0"


def test_document_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Document(
            tenant_id="tenant-1",
            source_filename="claim.tiff",
            detected_format=SourceFormat.TIFF,
            sha256="a" * 64,
            original_object=_object_ref(),
            pipeline_version="0.1.0",
            schema_version="1.0",
            not_a_real_field="oops",
        )


def test_bounding_box_normalizes_against_image_dimensions():
    box = BoundingBox(x0=100, y0=200, x1=300, y1=400, image_width=1000, image_height=2000)
    assert box.normalized() == (0.1, 0.1, 0.3, 0.2)


def test_extracted_field_requires_every_evidence_attribute():
    field = ExtractedField(
        field_name="patient_name",
        raw_value="DOE JOHN",
        normalized_value="Doe, John",
        confidence=0.94,
        page_number=1,
        bounding_box=BoundingBox(x0=1, y0=1, x1=2, y1=2, image_width=100, image_height=100),
        crop_object_uri="s3://idp-documents/crops/patient_name.png",
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        model_name="paddleocr-pp-ocrv5",
        model_version="5.0",
        template_version="cms1500-v1",
    )
    assert field.validation_status.value == "PENDING"
    assert field.candidates == []


def test_claim_all_fields_includes_header_and_service_line_fields():
    header_field = ExtractedField(
        field_name="total_charge",
        raw_value="150.00",
        confidence=0.9,
        page_number=1,
        bounding_box=BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=10, image_height=10),
        extraction_method=ExtractionMethod.TEMPLATE_RULES,
    )
    line_field = ExtractedField(
        field_name="procedure_code",
        raw_value="99213",
        confidence=0.9,
        page_number=1,
        bounding_box=BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=10, image_height=10),
        extraction_method=ExtractionMethod.TEMPLATE_RULES,
    )
    claim = Claim(
        document_id=uuid4(),
        tenant_id="tenant-1",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1.0",
        header_fields=[header_field],
        service_lines=[ServiceLine(line_number=1, fields=[line_field])],
    )
    assert claim.all_fields() == [header_field, line_field]


def test_compression_enum_covers_group4():
    assert CompressionType.CCITT_G4.value == "CCITT_G4"
