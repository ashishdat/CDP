from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRRequest
from workers.cascade.azure_read_adapter import (
    AzureReadEvidence,
    AzureReadShadowEngine,
)
from workers.cascade.engine_independence import independence_group
from workers.cascade.ppocr_next_adapter import PPOCRNextRecognitionEngine


class PaddleBackend:
    def predict(self, image):
        assert image.width > 100
        return "HAND WRITTEN", 0.81


class AzureBackend:
    def analyze(self, image_bytes):
        assert image_bytes.startswith(b"\x89PNG")
        return AzureReadEvidence("HAND WRITTEN", 0.91, True)


def request():
    return OCRRequest(
        document_id="hash",
        page_number=1,
        field_name="patient_name",
        field_type="name",
        form_type=ClaimFormType.CMS1500,
        image=Image.new("RGB", (50, 20), "white"),
        bounding_box=BoundingBox(
            x0=0, y0=0, x1=50, y1=20, image_width=50, image_height=20
        ),
    )


def test_ppocr_next_is_padded_recognition_only_review_evidence():
    candidate = PPOCRNextRecognitionEngine(backend=PaddleBackend()).recognize(request())[0]
    assert candidate.value == "HAND WRITTEN"
    assert "SHADOW_REVIEW_ONLY" in candidate.validation_results
    assert "white_border" in candidate.preprocessing_variant


def test_azure_is_disabled_until_all_phi_gates_are_approved():
    engine = AzureReadShadowEngine(backend=AzureBackend())
    try:
        engine.recognize(request())
    except RuntimeError as exc:
        assert "PHI contract" in str(exc)
    else:
        raise AssertionError("cloud OCR unexpectedly ran without authorization")


def test_authorized_azure_candidate_remains_review_only():
    engine = AzureReadShadowEngine(
        backend=AzureBackend(),
        authorized=True,
        region_approved=True,
        phi_contract_approved=True,
    )
    candidate = engine.recognize(request())[0]
    assert candidate.value == "HAND WRITTEN"
    assert "SHADOW_REVIEW_ONLY" in candidate.validation_results
    assert "HANDWRITTEN_STYLE" in candidate.validation_results


def test_paddle_versions_share_one_independence_group():
    assert independence_group("paddleocr") == "PADDLE_FAMILY"
    assert independence_group("paddleocr_recognition_only") == "PADDLE_FAMILY"
