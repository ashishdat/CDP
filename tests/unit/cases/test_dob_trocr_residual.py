"""Crop-scoped TrOCR DOB residual executor tests."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from packages.extraction_recovery.dob_trocr_residual import (
    DobTrOCRResidualResult,
    is_dob_handwriting_residual,
    maybe_attach_dob_trocr_to_field_row,
    residual_candidate_dict,
    run_dob_trocr_residual,
)
from workers.unstructured_extraction.trocr_adapter import TrOCRResult


@dataclass
class _FakeCropEngine:
    text: str
    confidence: float = 0.92

    def recognize_crop(self, crop: Image.Image, field_name: str) -> DobTrOCRResidualResult:
        assert crop.size[0] > 0 and crop.size[1] > 0
        assert field_name == "patient_dob"
        return DobTrOCRResidualResult(
            attempted=True,
            configured=True,
            review_only=False,
            value=self.text,
            raw_value=self.text,
            date_shaped=True,
            confidence=self.confidence,
            reason="TROCR_DATE_SHAPED",
            validation_results=("HANDWRITTEN_STYLE", "TROCR_CROP_RESIDUAL"),
        )


@dataclass
class _FakeTrOCRAdapter:
    text: str
    confidence: float = 0.91
    insufficient: bool = False

    def recognize(self, crop: Image.Image) -> TrOCRResult:
        assert crop.size[0] > 0
        return TrOCRResult(self.text, self.confidence, self.insufficient)


def test_is_dob_handwriting_residual_gates():
    assert is_dob_handwriting_residual(
        field_name="patient_dob",
        gap_class="HANDWRITING_UNREADABLE",
        local_accepted=False,
    )
    assert not is_dob_handwriting_residual(
        field_name="patient_dob",
        gap_class="HANDWRITING_UNREADABLE",
        local_accepted=True,
    )


def test_run_dob_trocr_residual_with_injected_engine():
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    result = run_dob_trocr_residual(
        image=img,
        bbox=(10, 10, 180, 70),
        field_name="patient_dob",
        gap_class="AMBIGUOUS_DIGIT_FRAGMENTS",
        engine=_FakeCropEngine("03/15/1968"),
    )
    assert result.attempted is True
    assert result.date_shaped is True
    assert result.value == "03/15/1968"
    assert "SHADOW_REVIEW_ONLY" not in result.validation_results
    cand = residual_candidate_dict(result, bbox=(10, 10, 180, 70), image_size=(200, 80))
    assert cand is not None
    assert cand["engine"] == "trocr"
    assert cand["shadow_review_only"] is False
    assert cand["bounding_box"]["x0"] == 10.0


def test_adapter_path_shapes_yy_dob():
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    result = run_dob_trocr_residual(
        image=img,
        bbox=(10, 10, 180, 70),
        field_name="patient_dob",
        gap_class="HANDWRITING_UNREADABLE",
        engine=_FakeTrOCRAdapter("03 15 68"),
    )
    assert result.attempted is True
    assert result.date_shaped is True
    assert result.value == "03/15/1968"


def test_attach_promotes_cascade_on_date_shaped():
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "patient_dob",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [],
        "cascade": {"accepted": False, "accept_reason": "EMPTY"},
        "status": "NO_VALUE",
    }
    updated = maybe_attach_dob_trocr_to_field_row(
        row,
        image=img,
        gap_class="HANDWRITING_UNREADABLE",
        engine=_FakeCropEngine("07/04/1955"),
    )
    assert updated["trocr_residual"]["attempted"] is True
    assert updated["trocr_residual"]["date_shaped"] is True
    assert updated["cascade"]["accepted"] is True
    assert updated["candidates"][0]["engine"] == "trocr"


def test_attach_skips_accepted_local_dob():
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "patient_dob",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [{"value": "01/02/2000", "engine": "paddleocr"}],
        "cascade": {"accepted": True, "accept_reason": "DATE_SHAPED"},
    }
    updated = maybe_attach_dob_trocr_to_field_row(
        row,
        image=img,
        gap_class="HANDWRITING_UNREADABLE",
        engine=_FakeCropEngine("03/15/1968"),
    )
    assert updated["trocr_residual"]["reason"] == "NOT_DOB_HANDWRITING_RESIDUAL"
    assert len(updated.get("candidates") or []) == 1
