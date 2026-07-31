from pathlib import Path

from PIL import Image

from packages.domain.common import ObjectRef
from packages.domain.document import Document
from packages.domain.enums import BundleType, SourceFormat
from workers.field_candidates import (
    CandidateStatus,
    DoclingCandidateProvider,
    DoclingText,
    FieldSpec,
    PreparedPage,
)


class FakeDocling:
    version = "test"
    model_name = "fake-docling"
    model_version = "1"

    def extract(self, image_path: Path) -> list[DoclingText]:
        assert image_path.exists()
        return [DoclingText("10 Main Street"), DoclingText("Boston MA 02110")]


def document() -> Document:
    return Document(
        tenant_id="test",
        source_filename="statement.png",
        detected_format=SourceFormat.PNG,
        bundle_type=BundleType.D_UNSTRUCTURED,
        sha256="a" * 64,
        original_object=ObjectRef(bucket="test", key="statement.png"),
        pipeline_version="test",
        schema_version="1",
    )


def test_docling_provider_preserves_reading_order_and_regional_bbox():
    provider = DoclingCandidateProvider(engine=FakeDocling())
    page = PreparedPage(
        page_number=1,
        image=Image.new("RGB", (1000, 800), "white"),
        image_sha256="b" * 64,
        family_scores={"insurance_statement": 0.9},
    )
    spec = FieldSpec(
        field_name="insured_address_block",
        field_type="address",
        critical=False,
        eligible_families=("insurance_statement",),
        normalized_region=(0.1, 0.2, 0.7, 0.5),
    )

    candidate = provider.extract_candidates(document(), [page], spec)[0]

    assert candidate.status == CandidateStatus.EVIDENCE
    assert candidate.raw_value == "10 Main Street\nBoston MA 02110"
    assert candidate.normalized_value == "10 Main Street Boston MA 02110"
    assert candidate.bounding_box == (100.0, 160.0, 700.0, 400.0)
    assert candidate.provider_name == "docling_layout_ocr"


def test_docling_provider_records_explicit_no_evidence_for_ineligible_page():
    provider = DoclingCandidateProvider(engine=FakeDocling())
    page = PreparedPage(
        page_number=1,
        image=Image.new("RGB", (100, 100), "white"),
        image_sha256="c" * 64,
        family_scores={"cms1500": 0.99},
    )
    spec = FieldSpec(
        field_name="patient_name",
        field_type="name",
        critical=True,
        eligible_families=("cms1500",),
    )

    candidate = provider.extract_candidates(document(), [page], spec)[0]

    assert candidate.status == CandidateStatus.NO_EVIDENCE
    assert candidate.failure_reason == "page_not_eligible_for_docling_pilot"
