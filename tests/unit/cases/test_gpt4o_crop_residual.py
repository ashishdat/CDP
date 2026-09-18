"""Unit tests for gpt-4o crop residual (DOB / member ID)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from PIL import Image

from packages.extraction_recovery.gpt4o_crop_residual import (
    Gpt4oCropResidualResult,
    dob_needs_gpt4o,
    id_local_needs_gpt4o,
    maybe_attach_gpt4o_crop_to_field_row,
    residual_candidate_dict,
    run_gpt4o_crop_residual,
)


@dataclass
class _FakeEngine:
    mapping: dict[str, Gpt4oCropResidualResult]

    def recognize_fields(
        self,
        crops: Mapping[str, Image.Image],
        *,
        field_types: Mapping[str, str],
        descriptions: Mapping[str, str],
        prior_candidates: Mapping[str, list[str]],
    ) -> Mapping[str, Gpt4oCropResidualResult]:
        assert crops
        return {name: self.mapping[name] for name in crops}


def test_dob_and_id_gate_helpers():
    assert dob_needs_gpt4o(
        local_accepted=False,
        trocr_shaped=False,
        azure_di_shaped=False,
        gap_class="HANDWRITING_UNREADABLE",
    )
    assert not dob_needs_gpt4o(
        local_accepted=False,
        trocr_shaped=True,
        azure_di_shaped=False,
        gap_class="HANDWRITING_UNREADABLE",
    )
    assert id_local_needs_gpt4o("Mrieniian", accepted=True)
    assert id_local_needs_gpt4o("20755", accepted=True)
    assert id_local_needs_gpt4o(
        "1a.INSURED'S I.D. NUMBER (For Program In Item 1)", accepted=True
    )
    assert not id_local_needs_gpt4o("949774145", accepted=True)


def test_run_and_attach_dob_accepts_shaped(monkeypatch):
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (240, 80), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "patient_dob": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="07/30/1977",
                raw_value="07/30/1977",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.99,
            )
        }
    )
    result = run_gpt4o_crop_residual(
        image=img,
        bbox=(10, 10, 200, 70),
        field_name="patient_dob",
        engine=engine,
    )
    assert result.shaped is True
    row = {
        "field": "patient_dob",
        "canonical_region": [10, 10, 200, 70],
        "ocr_region": [10, 10, 200, 70],
        "candidates": [{"value": "7:30.77", "engine": "azure_document_intelligence_read"}],
        "cascade": {"accepted": False},
        "trocr_residual": {"date_shaped": False, "review_only": False},
        "azure_di_residual": {"date_shaped": False, "review_only": True, "value": "7:30.77"},
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(
        row, image=img, gap_class="HANDWRITING_UNREADABLE", engine=engine
    )
    assert updated["cascade"]["accepted"] is True
    assert updated["gpt4o_crop_residual"]["shaped"] is True
    assert updated["candidates"][0]["engine"] == "azure_gpt4o_crop"
    cand = residual_candidate_dict(
        result, bbox=(10, 10, 200, 70), image_size=(240, 80)
    )
    assert cand is not None
    assert cand["value"] == "07/30/1977"


def test_attach_id_rejects_chrome_hallucination(monkeypatch):
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (400, 80), color=(255, 255, 255))

    class _ChromeEngine:
        def recognize_fields(self, crops, **kwargs):
            from packages.extraction_recovery.gpt4o_crop_residual import (
                Gpt4oCropResidualResult,
                _shape_id,
            )

            raw = "7GND0CSL07N0BER"
            shaped_val, shaped = _shape_id(raw)
            return {
                "insured_id_number": Gpt4oCropResidualResult(
                    attempted=True,
                    configured=True,
                    review_only=True,
                    value=shaped_val,
                    raw_value=raw,
                    shaped=shaped,
                    insufficient_evidence=False,
                    reason="GPT4O_UNSHAPED" if not shaped else "GPT4O_SHAPED",
                    confidence=0.95,
                )
            }

    row = {
        "field": "insured_id_number",
        "canonical_region": [10, 10, 380, 70],
        "ocr_region": [10, 10, 380, 70],
        "candidates": [{"value": "Porowennnoss", "engine": "tesseract"}],
        "cascade": {"accepted": False},
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(
        row, image=img, engine=_ChromeEngine()
    )
    # BER-suffix chrome must not promote.
    assert updated.get("cascade", {}).get("accepted") is not True
    meta = updated.get("gpt4o_crop_residual") or {}
    assert meta.get("shaped") is False


def test_attach_id_promotes_clean_member_id(monkeypatch):
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (400, 80), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "insured_id_number": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="949774145",
                raw_value="949774145",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.99,
            )
        }
    )
    row = {
        "field": "insured_id_number",
        "canonical_region": [10, 10, 380, 70],
        "ocr_region": [10, 10, 380, 70],
        "candidates": [{"value": "Mrieniian", "engine": "paddleocr"}],
        "cascade": {
            "accepted": True,
            "accept_reason": "ID_SHAPED",
            "steps": [
                {"accepted": True, "selected_value": "Mrieniian", "variant_id": "id_value_band"}
            ],
        },
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(row, image=img, engine=engine)
    assert updated["cascade"]["accepted"] is True
    assert "GPT4O_CROP_RESIDUAL" in updated["cascade"]["accept_reason"]
    assert updated["candidates"][0]["value"] == "949774145"


def test_attach_id_fires_on_same_length_digit_conflict(monkeypatch):
    """Long shaped locals that disagree still invoke gpt-4o as tie-break."""
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (400, 80), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "insured_id_number": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="909293380",
                raw_value="909293380",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.97,
            )
        }
    )
    row = {
        "field": "insured_id_number",
        "canonical_region": [10, 10, 380, 70],
        "ocr_region": [10, 10, 380, 70],
        "candidates": [
            {"value": "909295500", "engine": "paddleocr"},
            {"value": "909293380", "engine": "rapidocr"},
        ],
        "cascade": {
            "accepted": True,
            "accept_reason": "ID_SHAPED",
            "steps": [
                {
                    "accepted": True,
                    "selected_value": "909293380",
                    "variant_id": "id_value_band",
                }
            ],
        },
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(row, image=img, engine=engine)
    assert updated["gpt4o_crop_residual"]["shaped"] is True
    assert updated["candidates"][0]["value"] == "909293380"
    assert "GPT4O_CROP_RESIDUAL" in updated["cascade"]["accept_reason"]


def test_dob_cell_split_retry_after_full_box_abstain(monkeypatch):
    """HJHO.011-class: full-box abstain → MM/DD/YY strip retry shapes."""
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (240, 80), color=(255, 255, 255))

    class _AbstainThenShape:
        def __init__(self) -> None:
            self.calls = 0
            self.descriptions: list[str] = []

        def recognize_fields(self, crops, **kwargs):
            self.calls += 1
            desc = (kwargs.get("descriptions") or {}).get("patient_dob") or ""
            self.descriptions.append(desc)
            if self.calls == 1:
                return {
                    "patient_dob": Gpt4oCropResidualResult(
                        attempted=True,
                        configured=True,
                        review_only=True,
                        value=None,
                        raw_value=None,
                        shaped=False,
                        insufficient_evidence=True,
                        reason="GPT4O_ABSTAIN",
                    )
                }
            return {
                "patient_dob": Gpt4oCropResidualResult(
                    attempted=True,
                    configured=True,
                    review_only=True,
                    value="04/11/1998",
                    raw_value="04/11/1998",
                    shaped=True,
                    insufficient_evidence=False,
                    reason="GPT4O_SHAPED",
                    confidence=0.98,
                )
            }

    engine = _AbstainThenShape()
    result = run_gpt4o_crop_residual(
        image=img,
        bbox=(10, 10, 200, 70),
        field_name="patient_dob",
        prior_candidates=["7:30.77"],
        engine=engine,
    )
    assert engine.calls == 2
    assert "Prior OCR saw: 7:30.77" in engine.descriptions[0]
    assert "Three cropped" in engine.descriptions[1]
    assert result.shaped is True
    assert result.reason == "GPT4O_CELL_SPLIT_SHAPED"
    assert "GPT4O_CELL_SPLIT" in result.validation_results


def test_charge_needs_gpt4o_and_shapes_currency():
    from packages.extraction_recovery.gpt4o_crop_residual import (
        _shape_charge,
        charge_needs_gpt4o,
    )

    assert charge_needs_gpt4o(
        local_accepted=False, azure_di_shaped=False, gap_class="CHARGE_LOCAL_EXHAUSTED"
    )
    assert not charge_needs_gpt4o(
        local_accepted=True, azure_di_shaped=False, gap_class="CHARGE_LOCAL_EXHAUSTED"
    )
    assert not charge_needs_gpt4o(
        local_accepted=False, azure_di_shaped=True, gap_class="CHARGE_LOCAL_EXHAUSTED"
    )
    shaped, ok = _shape_charge("TOTAL CHARGE 233.00")
    assert ok and shaped == "233.00"
    shaped, ok = _shape_charge("1.00")
    assert not ok


def test_attach_charge_promotes_shaped_box28(monkeypatch):
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (240, 80), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "total_charge": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="233.00",
                raw_value="233.00",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.97,
            )
        }
    )
    # Force shaped=True through recognizer path (FakeEngine returns pre-shaped).
    row = {
        "field": "total_charge",
        "canonical_region": [10, 10, 200, 70],
        "ocr_region": [10, 10, 200, 70],
        "candidates": [],
        "cascade": {"accepted": False, "accept_reason": "EMPTY"},
        "azure_di_residual": {
            "currency_shaped": False,
            "review_only": True,
            "value": None,
            "reason": "AZURE_DI_UNSHAPED",
        },
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(
        row, image=img, gap_class="CHARGE_LOCAL_EXHAUSTED", engine=engine
    )
    assert updated["cascade"]["accepted"] is True
    assert updated["cascade"]["value"] == "233.00"
    assert updated["gpt4o_crop_residual"]["shaped"] is True
    assert updated["candidates"][0]["engine"] == "azure_gpt4o_crop"