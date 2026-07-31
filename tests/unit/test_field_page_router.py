from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate
from workers.unstructured_extraction.evidence_selector import PageFieldEvidence
from workers.unstructured_extraction.field_page_router import (
    FieldLevelPageRouter,
    RequiredField,
)


class Provider:
    def candidates(self, *, document_id, page_number, field_name):
        confidence = {
            ("name", 2): .95, ("name", 3): .5,
            ("diagnosis", 2): .4, ("diagnosis", 3): .95,
        }[(field_name, page_number)]
        value = field_name if confidence > .5 else None
        candidate = OCRCandidate(
            value=value, raw_value=value or "", engine="test", model_name="test",
            model_version="1", preprocessing_variant="original",
            raw_confidence=confidence, calibrated_confidence=confidence,
            bounding_box=BoundingBox(
                x0=0, y0=0, x1=1, y1=1, image_width=10, image_height=10
            ),
            latency_ms=1,
        )
        return [PageFieldEvidence(
            field_name, page_number, "claim", candidate,
            .9, .9, .9, value is not None, anchor_phrase=field_name,
        )]


def test_fields_route_independently_across_all_pages():
    result = FieldLevelPageRouter(Provider()).route(
        document_id="doc", page_numbers=[2, 3],
        required_fields=[RequiredField("name", True), RequiredField("diagnosis", True)],
    )
    assert result[0].decision.selected.page_number == 2
    assert result[1].decision.selected.page_number == 3
