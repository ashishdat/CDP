"""DI confirms Claude on a name, and DI+partner mints charge E2 without place-shifts."""

from PIL import Image

from packages.evidence.builder import build_evidence_bundle
from packages.extraction_recovery.name_azure_di_confirm import (
    maybe_confirm_name_with_azure_di,
)
from packages.ocr.contracts import OCRCandidate
from packages.domain.common import BoundingBox


def _cand(engine, value, conf=0.9):
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="test",
        preprocessing_variant="test",
        raw_confidence=conf,
        calibrated_confidence=conf,
        bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=20, image_height=20),
        latency_ms=0.0,
    )


def test_name_di_adopts_claude_spelling_when_they_agree():
    row = {
        "field": "patient_name",
        "ocr_region": [10, 10, 80, 40],
        "candidates": [
            {"engine": "rapidocr", "value": "CMOMXAUONI ANUA Y"},
            {"engine": "anthropic_claude_crop", "value": "FRANCAVILLA, THOMAS J"},
        ],
        "cascade": {"accepted": True, "value": "CMOMXAUONI ANUA Y"},
    }
    updated = maybe_confirm_name_with_azure_di(
        row,
        image=Image.new("RGB", (100, 40), "white"),
        reader=lambda _image, _field: "FRANCAVILLA, THOMAS J",
    )
    assert updated["cascade"]["value"] == "FRANCAVILLA, THOMAS J"
    assert updated["cascade"]["accept_reason"] == "NAME_DI_CLAUDE_AGREEMENT"
    assert updated["candidates"][0]["engine"] == "azure_document_intelligence_read"


def test_name_di_does_not_supersede_when_it_disagrees():
    row = {
        "field": "patient_name",
        "ocr_region": [10, 10, 80, 40],
        "candidates": [
            {"engine": "rapidocr", "value": "CMOMXAUONI ANUA Y"},
            {"engine": "anthropic_claude_crop", "value": "CHANQUIANI, ANYA M"},
        ],
        "cascade": {"accepted": True, "value": "CMOMXAUONI ANUA Y"},
    }
    updated = maybe_confirm_name_with_azure_di(
        row,
        image=Image.new("RGB", (100, 40), "white"),
        reader=lambda _image, _field: "Chanquiani, Anyja M",
    )
    assert updated["cascade"]["value"] == "CMOMXAUONI ANUA Y"
    assert any(a.get("reason") == "NAME_DI_DISAGREES" for a in updated["attempts"])


def test_charge_di_rapid_mints_e2_but_place_shift_does_not():
    agreed = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("azure_document_intelligence_read", "495.00"),
            _cand("rapidocr", "495.00"),
            _cand("paddleocr", "405.00"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID", "HARD_VALIDATION_PASSED"},
        hard_validation_passed=True,
    )
    e2 = [
        item
        for item in agreed.items
        if item.evidence_class.value == "E2" and item.independent
    ]
    assert e2 and e2[0].metadata.get("agreement_type") == "CHARGE_DI_PARTNER_AGREEMENT"

    shifted = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("azure_document_intelligence_read", "4972.00"),
            _cand("rapidocr", "4972.00"),
            _cand("paddleocr", "49.72"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID"},
        hard_validation_passed=True,
    )
    assert not any(
        item.evidence_class.value == "E2" and item.independent for item in shifted.items
    )
