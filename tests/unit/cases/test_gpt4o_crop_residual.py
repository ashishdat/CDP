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


def test_id_needs_gpt4o_skips_when_locals_already_settled():
    """paddle+rapid agreement on a shaped ID must not spend Claude/DI."""
    from packages.extraction_recovery.gpt4o_crop_residual import id_needs_gpt4o

    settled = [
        {"value": "0000007267", "engine": "paddleocr"},
        {"value": "0000007267", "engine": "rapidocr"},
        {"value": "eee ae | ONNNAAIVKRT", "engine": "tesseract"},
    ]
    assert not id_needs_gpt4o(
        "0000007267", accepted=True, candidates=settled
    )
    # Digit twins still need vision.
    conflict = [
        {"value": "909295500", "engine": "paddleocr"},
        {"value": "909293380", "engine": "rapidocr"},
    ]
    assert id_needs_gpt4o("909295500", accepted=True, candidates=conflict)


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


def test_attach_dob_rejects_vision_only_digit(monkeypatch):
    """A lone local digit is not corroboration. GPT must not STP 07/02/1980."""
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (240, 80), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "patient_dob": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="07/02/1980",
                raw_value="07/02/1980",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.99,
            )
        }
    )
    row = {
        "field": "patient_dob",
        "canonical_region": [10, 10, 200, 70],
        "ocr_region": [10, 10, 200, 70],
        "candidates": [{"value": "1", "raw_value": "1", "engine": "rapidocr"}],
        "cascade": {"accepted": False},
        "trocr_residual": {"date_shaped": False, "review_only": False},
        "azure_di_residual": {"date_shaped": False, "review_only": True},
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(
        row, image=img, gap_class="HANDWRITING_UNREADABLE", engine=engine
    )
    assert updated.get("cascade", {}).get("accepted") is not True
    meta = updated.get("gpt4o_crop_residual") or {}
    assert "GPT_DOB_NEEDS_LOCAL_DIGITS" in str(meta.get("reason"))


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
    assert charge_needs_gpt4o(
        local_accepted=True,
        azure_di_shaped=True,
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        candidates=[
            {"engine": "azure_document_intelligence_read", "value": "660.00"},
            {"engine": "paddleocr", "value": "50.00"},
        ],
    )
    # DIGITS_FIRST accepted but place-shift rivals → still need gpt-4o.
    assert charge_needs_gpt4o(
        local_accepted=True,
        azure_di_shaped=False,
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        candidates=[
            {"engine": "rapidocr", "value": "222.22"},
            {"engine": "paddleocr", "value": "2221.22"},
        ],
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
    # Redesign: GPT is not sole monetary authority — candidate attached, not AUTO.
    assert updated["gpt4o_crop_residual"]["shaped"] is True
    assert updated["candidates"][0]["engine"] == "azure_gpt4o_crop"
    assert updated["candidates"][0]["value"] == "233.00"
    assert updated["cascade"]["accepted"] is False
    assert "GPT_NOT_MONETARY_AUTHORITY" in updated["gpt4o_crop_residual"]["reason"]
    assert updated["acceptance_risk"]["review_recommended"] is True
    assert updated["acceptance_risk"]["method"] == "gpt_not_monetary_authority"


def test_attach_charge_promotes_when_local_corroborates(monkeypatch):
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
    row = {
        "field": "total_charge",
        "canonical_region": [10, 10, 200, 70],
        "ocr_region": [10, 10, 200, 70],
        "candidates": [{"value": "233.00", "engine": "paddleocr"}],
        "cascade": {"accepted": False, "accept_reason": "EMPTY", "value": ""},
        "azure_di_residual": {"currency_shaped": False, "value": None},
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(
        row, image=img, gap_class="CHARGE_LOCAL_EXHAUSTED", engine=engine
    )
    assert updated["cascade"]["accepted"] is True
    assert updated["cascade"]["value"] == "233.00"

def test_name_conflict_triggers_gpt4o_and_accepts_shaped(monkeypatch):
    from packages.extraction_recovery.gpt4o_crop_residual import name_needs_gpt4o

    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    conflict_cands = [
        {"value": "THOMAS.DARLENE.M", "engine": "paddleocr"},
        {"value": "THOMAS, DARLENE", "engine": "rapidocr"},
    ]
    assert name_needs_gpt4o(
        local_accepted=True,
        candidates=conflict_cands,
        gap_class=None,
    )
    assert not name_needs_gpt4o(
        local_accepted=True,
        candidates=[
            {"value": "THOMAS DARLENE", "engine": "paddleocr"},
            {"value": "THOMAS DARLENE", "engine": "rapidocr"},
        ],
    )
    assert name_needs_gpt4o(
        local_accepted=True,
        candidates=[{"value": "FRANCAVLLA, THOMAS J", "engine": "rapidocr"}],
    )
    assert name_needs_gpt4o(
        local_accepted=True,
        candidates=[
            {"value": "CMOXXALUONI, ANUA Y", "engine": "rapidocr"},
            {"value": "M", "engine": "paddleocr"},
        ],
    )
    assert name_needs_gpt4o(
        local_accepted=True,
        candidates=[
            {"value": "KIVERALARAA", "engine": "paddleocr"},
            {"value": "RIVERA LARAA", "engine": "rapidocr"},
        ],
    )
    img = Image.new("RGB", (240, 80), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "patient_name": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="THOMAS DARLENE",
                raw_value="THOMAS DARLENE",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.98,
            )
        }
    )
    row = {
        "field": "patient_name",
        "canonical_region": [10, 10, 200, 70],
        "ocr_region": [10, 10, 200, 70],
        "candidates": conflict_cands,
        "cascade": {
            "accepted": True,
            "accept_reason": "NAME_SHAPED",
            "value": "THOMAS.DARLENE.M",
        },
    }
    updated = maybe_attach_gpt4o_crop_to_field_row(
        row, image=img, gap_class="NAME_ENGINE_CONFLICT", engine=engine
    )
    assert updated["gpt4o_crop_residual"]["shaped"] is True
    assert updated["cascade"]["accepted"] is True
    assert updated["cascade"]["value"] == "THOMAS DARLENE"
    assert updated["candidates"][0]["engine"] == "azure_gpt4o_crop"


def test_confusable_name_split_accepts_only_with_local(monkeypatch):
    """KIVERA vs RIVERA calls vision; an unrelated GPT name does not replace locals."""
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (240, 80), color=(255, 255, 255))
    locals_ = [
        {"value": "KIVERALARAA", "engine": "paddleocr"},
        {"value": "RIVERA LARAA", "engine": "rapidocr"},
    ]
    reject = _FakeEngine(
        {
            "patient_name": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="JANE DOE",
                raw_value="JANE DOE",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.99,
            )
        }
    )
    rejected = maybe_attach_gpt4o_crop_to_field_row(
        {
            "field": "patient_name",
            "canonical_region": [10, 10, 200, 70],
            "ocr_region": [10, 10, 200, 70],
            "candidates": list(locals_),
            "cascade": {
                "accepted": True,
                "accept_reason": "NAME_SHAPED",
                "value": "KIVERALARAA",
            },
        },
        image=img,
        engine=reject,
    )
    assert rejected["cascade"]["value"] == "KIVERALARAA"
    assert "GPT_NAME_NEEDS_LOCAL" in str(
        (rejected.get("gpt4o_crop_residual") or {}).get("reason")
    )
    accept = _FakeEngine(
        {
            "patient_name": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="RIVERA LARAA",
                raw_value="RIVERA LARAA",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.99,
            )
        }
    )
    updated = maybe_attach_gpt4o_crop_to_field_row(
        {
            "field": "patient_name",
            "canonical_region": [10, 10, 200, 70],
            "ocr_region": [10, 10, 200, 70],
            "candidates": list(locals_),
            "cascade": {
                "accepted": True,
                "accept_reason": "NAME_SHAPED",
                "value": "KIVERALARAA",
            },
        },
        image=img,
        engine=accept,
    )
    assert updated["cascade"]["accepted"] is True
    assert updated["cascade"]["value"] == "RIVERA LARAA"


def test_empty_finance_line_sweep_recovers_gpt_shaped_amount(monkeypatch):
    from packages.extraction_recovery.gpt4o_crop_residual import (
        recover_empty_financial_service_lines,
    )

    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_EMPTY_FINANCE", "1")
    monkeypatch.setenv("CDP_GPT4O_EMPTY_FINANCE_MAX_LINES", "2")
    img = Image.new("RGB", (400, 400), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "charges": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="18.00",
                raw_value="18.00",
                shaped=True,
                insufficient_evidence=False,
                reason="GPT4O_SHAPED",
                confidence=0.91,
            )
        }
    )

    def local_recognize(bbox):
        return (
            [
                {
                    "value": "18.00",
                    "raw_value": "18",
                    "engine": "paddleocr",
                }
            ],
            [{"engine": "paddleocr", "reason": "OBSERVED"}],
            "OBSERVED",
        )

    lines = recover_empty_financial_service_lines(
        image=img,
        line_bboxes=[(10, 10, 100, 50), (10, 60, 100, 100)],
        engine=engine,
        local_recognize=local_recognize,
    )
    assert len(lines) == 2
    assert lines[0]["charges"] == "18.00"
    assert lines[0]["status"] == "OBSERVED"
    engines = {c["engine"] for c in lines[0]["candidates"]}
    assert "azure_gpt4o_crop" in engines
    assert "paddleocr" in engines
    assert "EMPTY_FINANCE_GPT4O_SWEEP" in lines[0]["router_reason"]


def test_empty_finance_line_sweep_abstains_without_inventing(monkeypatch):
    from packages.extraction_recovery.gpt4o_crop_residual import (
        recover_empty_financial_service_lines,
    )

    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_EMPTY_FINANCE", "1")
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    engine = _FakeEngine(
        {
            "charges": Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value=None,
                raw_value=None,
                shaped=False,
                insufficient_evidence=True,
                reason="GPT4O_ABSTAIN",
                confidence=0.9,
            )
        }
    )
    lines = recover_empty_financial_service_lines(
        image=img,
        line_bboxes=[(10, 10, 80, 40)],
        engine=engine,
    )
    assert lines == []


def test_charge_expanded_crop_retry_on_abstain(monkeypatch):
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")
    img = Image.new("RGB", (300, 300), color=(255, 255, 255))
    calls = {"n": 0}

    class _ExpandEngine:
        def recognize_fields(
            self,
            crops,
            *,
            field_types,
            descriptions,
            prior_candidates,
        ):
            calls["n"] += 1
            # First (tight) abstain; expanded succeeds.
            if calls["n"] == 1:
                return {
                    "total_charge": Gpt4oCropResidualResult(
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
                "total_charge": Gpt4oCropResidualResult(
                    attempted=True,
                    configured=True,
                    review_only=True,
                    value="1165.00",
                    raw_value="1165.00",
                    shaped=True,
                    insufficient_evidence=False,
                    reason="GPT4O_SHAPED",
                    confidence=0.93,
                )
            }

    result = run_gpt4o_crop_residual(
        image=img,
        bbox=(100, 100, 140, 130),
        field_name="total_charge",
        engine=_ExpandEngine(),
    )
    assert result.shaped is True
    assert result.value == "1165.00"
    assert result.reason == "GPT4O_EXPANDED_CHARGE_SHAPED"
    assert calls["n"] >= 2
