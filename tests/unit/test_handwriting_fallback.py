from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ExtractionMethod, ValidationStatus
from packages.domain.extraction import ExtractedField
from workers.unstructured_extraction.handwriting_service import HandwritingFallbackService
from workers.unstructured_extraction.trocr_adapter import TrOCRResult


class FakeRecognizer:
    def __init__(self, result: TrOCRResult) -> None:
        self.result = result
        self.calls = 0

    def recognize(self, crop: Image.Image) -> TrOCRResult:
        self.calls += 1
        return self.result

    def recognize_batch(self, crops: list[Image.Image]) -> list[TrOCRResult]:
        self.calls += len(crops)
        return [self.result for _ in crops]


def _field(name: str, status: ValidationStatus) -> ExtractedField:
    return ExtractedField(
        field_name=name,
        raw_value="old",
        confidence=0.4,
        page_number=1,
        bounding_box=BoundingBox(
            x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100
        ),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        validation_status=status,
    )


def test_handwriting_never_reads_or_overwrites_valid_field():
    recognizer = FakeRecognizer(TrOCRResult("new", 0.9, False))
    service = HandwritingFallbackService(recognizer, "trocr", "1")
    result = service.request_for_failed_fields(
        [_field("valid", ValidationStatus.VALID)],
        {"valid": Image.new("RGB", (20, 10))},
    )
    assert result == {}
    assert recognizer.calls == 0


def test_handwriting_returns_named_candidate_for_invalid_crop():
    recognizer = FakeRecognizer(TrOCRResult("ASHISH SINGH", 0.91, False))
    service = HandwritingFallbackService(recognizer, "trocr", "1")
    result = service.request_for_failed_fields(
        [_field("patient_name", ValidationStatus.INVALID)],
        {"patient_name": Image.new("RGB", (20, 10))},
    )
    assert result["patient_name"].source == ExtractionMethod.TROCR
    assert result["patient_name"].raw_text == "ASHISH SINGH"


def test_handwriting_discards_low_evidence_candidate():
    recognizer = FakeRecognizer(TrOCRResult("guess", 0.2, True))
    service = HandwritingFallbackService(recognizer, "trocr", "1")
    result = service.request_for_failed_fields(
        [_field("patient_name", ValidationStatus.NEEDS_REVIEW)],
        {"patient_name": Image.new("RGB", (20, 10))},
    )
    assert result == {}
