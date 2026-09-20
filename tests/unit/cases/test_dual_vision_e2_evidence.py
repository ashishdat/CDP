"""Dual Claude+gpt-4o agreement mints independent E2 for name/DOB."""

from packages.evidence.builder import build_evidence_bundle
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
        bounding_box=BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1),
        latency_ms=0.0,
    )


def test_dual_vision_mints_independent_e2_for_dob():
    bundle = build_evidence_bundle(
        field_name="patient_dob",
        candidates=[
            _cand("anthropic_claude_crop", "11/02/1980"),
            _cand("azure_gpt4o_crop", "11/02/1980"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"DATE_VALID", "FORMAT_VALID"},
        hard_validation_passed=True,
    )
    e2 = [
        i
        for i in bundle.items
        if i.evidence_class.value == "E2" and i.independent
    ]
    assert e2, bundle.items
    assert e2[0].evidence_type == "OCR_AGREEMENT_INDEPENDENT"
    assert e2[0].metadata.get("agreement_type") == "DUAL_VISION_VENDOR_AGREEMENT"


def test_dual_vision_mints_independent_e2_for_name():
    bundle = build_evidence_bundle(
        field_name="patient_name",
        candidates=[
            _cand("anthropic_claude_crop", "NOVOTNY, ANNIE"),
            _cand("azure_gpt4o_crop", "NOVOTNY ANNIE"),
            _cand("paddleocr", "NOVOTNY INNIE"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID"},
        hard_validation_passed=True,
    )
    e2 = [
        i
        for i in bundle.items
        if i.evidence_class.value == "E2"
        and i.independent
        and i.evidence_type == "OCR_AGREEMENT_INDEPENDENT"
    ]
    assert e2
