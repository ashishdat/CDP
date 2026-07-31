from uuid import uuid4

from PIL import Image

from packages.domain.common import ObjectRef
from packages.domain.document import Document
from packages.domain.enums import DocumentStatus, SourceFormat
from workers.field_candidates.contracts import (
    CandidateStatus,
    FieldSpec,
    PreparedPage,
)
from workers.field_candidates.pipeline import AllPageCandidatePipeline, CandidateStore
from workers.field_candidates.providers import PsychologicalReceiptProvider
from workers.page_detection.text_extraction import TextLine


def _document():
    return Document(
        document_id=uuid4(), tenant_id="test", source_filename="test.tif",
        detected_format=SourceFormat.TIFF, sha256="a" * 64, page_count=2,
        status=DocumentStatus.PREPARED,
        original_object=ObjectRef(bucket="test", key="test.tif"),
        pipeline_version="1", schema_version="1",
    )


def test_pipeline_records_no_evidence_and_waits_for_every_page(tmp_path):
    image = Image.new("RGB", (100, 100), "white")
    pages = [
        PreparedPage(
            1, image, "page1",
            (TextLine("Receipt", 1, 1, 20, 10, .9),),
            {"psychological_receipt": .9},
        ),
        PreparedPage(
            2, image, "page2",
            (
                TextLine("Client:", 1, 1, 20, 10, .9),
                TextLine("JANE DOE", 25, 1, 70, 10, .95),
            ),
            {"psychological_receipt": .9},
        ),
    ]
    candidates, outcomes = AllPageCandidatePipeline(
        [PsychologicalReceiptProvider()], CandidateStore(tmp_path)
    ).run(
        _document(), pages,
        [FieldSpec(
            "patient_name", "person_name", True,
            anchors=("client:",), eligible_families=("psychological_receipt",),
        )],
    )
    assert len(candidates) == 2
    assert candidates[0].status == CandidateStatus.NO_EVIDENCE
    assert candidates[0].failure_reason
    assert outcomes[0].completeness.routing_ready
    assert outcomes[0].completeness.pages_attempted == 2
    assert outcomes[0].decision.selected.page_number == 2


def test_candidate_cache_resumes_without_duplicate_inference(tmp_path):
    class CountingProvider(PsychologicalReceiptProvider):
        calls = 0

        def extract_candidates(self, document, pages, field_spec):
            self.calls += 1
            return super().extract_candidates(document, pages, field_spec)

    provider = CountingProvider()
    image = Image.new("RGB", (100, 100), "white")
    pages = [PreparedPage(1, image, "same", (), {"psychological_receipt": .9})]
    fields = [FieldSpec("name", "text", False, anchors=("name",))]
    pipeline = AllPageCandidatePipeline([provider], CandidateStore(tmp_path))
    pipeline.run(_document(), pages, fields)
    pipeline.run(_document(), pages, fields)
    assert provider.calls == 1
