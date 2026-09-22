"""Crop-scoped Azure DI DOB residual executor tests."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from packages.extraction_recovery.dob_azure_di_residual import (
    DobAzureDiResidualResult,
    is_dob_handwriting_residual,
    maybe_attach_dob_azure_di_to_field_row,
    residual_candidate_dict,
    run_dob_azure_di_residual,
)


@dataclass
class _FakeCropEngine:
    text: str

    def recognize_crop(self, crop: Image.Image, field_name: str) -> DobAzureDiResidualResult:
        assert crop.size[0] > 0 and crop.size[1] > 0
        assert field_name == "patient_dob"
        return DobAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=True,
            value=self.text,
            raw_value=self.text,
            date_shaped=True,
            reason="AZURE_DI_DATE_SHAPED_REVIEW_ONLY",
            validation_results=("SHADOW_REVIEW_ONLY", "HANDWRITTEN_STYLE"),
        )


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
    assert not is_dob_handwriting_residual(
        field_name="total_charge",
        gap_class="HANDWRITING_UNREADABLE",
        local_accepted=False,
    )


def test_run_dob_azure_di_residual_with_injected_engine():
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    result = run_dob_azure_di_residual(
        image=img,
        bbox=(10, 10, 180, 70),
        field_name="patient_dob",
        gap_class="AMBIGUOUS_DIGIT_FRAGMENTS",
        engine=_FakeCropEngine("03/15/1968"),
    )
    assert result.attempted is True
    assert result.date_shaped is True
    assert result.value == "03/15/1968"
    assert "SHADOW_REVIEW_ONLY" in result.validation_results
    cand = residual_candidate_dict(result)
    assert cand is not None
    assert cand["engine"] == "azure_document_intelligence_read"
    assert cand["shadow_review_only"] is True


def test_attach_skips_accepted_local_dob():
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "patient_dob",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [{"value": "01/02/2000", "engine": "paddleocr"}],
        "cascade": {"accepted": True, "accept_reason": "DATE_SHAPED"},
    }
    updated = maybe_attach_dob_azure_di_to_field_row(
        row,
        image=img,
        gap_class="HANDWRITING_UNREADABLE",
        engine=_FakeCropEngine("03/15/1968"),
    )
    # Stop ladder: cascade-accepted DOB skips DI entirely.
    assert (updated.get("cloud_stop_ladder") or {}).get("skipped") == "LOCALS_SETTLED"
    assert "azure_di_residual" not in updated
    assert len(updated.get("candidates") or []) == 1


def test_attach_appends_shadow_candidate_on_miss():
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "patient_dob",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [],
        "cascade": {"accepted": False, "accept_reason": "EMPTY"},
    }
    updated = maybe_attach_dob_azure_di_to_field_row(
        row,
        image=img,
        gap_class="HANDWRITING_UNREADABLE",
        engine=_FakeCropEngine("07/04/1955"),
    )
    assert updated["azure_di_residual"]["attempted"] is True
    assert updated["azure_di_residual"]["date_shaped"] is True
    assert any(
        c.get("engine") == "azure_document_intelligence_read"
        for c in updated["candidates"]
    )
