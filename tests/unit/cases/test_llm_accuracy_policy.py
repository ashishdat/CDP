"""Accuracy-first LLM policy + vision+local charge E4."""

from __future__ import annotations

from packages.domain.common import BoundingBox
from packages.evidence.builder import build_evidence_bundle
from packages.extraction_recovery.llm_accuracy_policy import (
    charge_accuracy_needs_di,
    charge_accuracy_needs_vision,
    force_cloud_despite_budget,
    name_force_despite_budget,
)
from packages.ocr.contracts import OCRCandidate


def _cand(engine: str, value: str, conf: float = 0.9) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="test",
        preprocessing_variant="test",
        raw_confidence=conf,
        calibrated_confidence=conf,
        bounding_box=BoundingBox(
            x0=0, y0=0, x1=10, y1=10, image_width=20, image_height=20
        ),
        latency_ms=0.0,
    )


def test_zero_line_dual_local_needs_di():
    row = {
        "field": "total_charge",
        "candidates": [
            {"engine": "paddleocr", "value": "125.00"},
            {"engine": "rapidocr", "value": "125.00"},
        ],
        "observed_line_charges": [],
    }
    assert charge_accuracy_needs_di(row) is True
    assert force_cloud_despite_budget("total_charge", row) is True


def test_zero_line_skips_vision_when_di_agrees():
    row = {
        "field": "total_charge",
        "candidates": [
            {"engine": "paddleocr", "value": "125.00"},
            {"engine": "rapidocr", "value": "125.00"},
        ],
        "observed_line_charges": [],
    }
    assert (
        charge_accuracy_needs_vision(
            row, di_ready=True, di_agrees_local=True, observed_line_charges=[]
        )
        is False
    )
    assert (
        charge_accuracy_needs_vision(
            row, di_ready=False, di_agrees_local=False, observed_line_charges=[]
        )
        is True
    )


def test_place_shift_vs_lines_always_needs_vision():
    row = {
        "field": "total_charge",
        "candidates": [
            {"engine": "paddleocr", "value": "251.00"},
            {"engine": "rapidocr", "value": "251.00"},
        ],
        "observed_line_charges": ["2.51"],
    }
    assert charge_accuracy_needs_di(row) is True
    assert (
        charge_accuracy_needs_vision(
            row,
            di_ready=True,
            di_agrees_local=True,
            observed_line_charges=["2.51"],
        )
        is True
    )


def test_vision_local_mints_strong_e4_without_di():
    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("paddleocr", "125.00"),
            _cand("rapidocr", "125.00"),
            _cand("anthropic_claude_crop", "125.00"),
        ],
        registration_confidence=0.9,
        wrong_crop_suspected=False,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        hard_validation_passed=True,
    )
    facts = {
        (item.metadata or {}).get("fact")
        for item in bundle.items
        if item.metadata
    }
    assert "CHARGE_VISION_LOCAL_CONFIRMED" in facts


def test_vision_local_does_not_mint_e4_on_place_shift_rival():
    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("paddleocr", "200.00"),
            _cand("anthropic_claude_crop", "200.00"),
            _cand("rapidocr", "2001.00"),
        ],
        registration_confidence=0.9,
        wrong_crop_suspected=False,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        hard_validation_passed=True,
    )
    facts = {
        (item.metadata or {}).get("fact")
        for item in bundle.items
        if item.metadata
    }
    assert "CHARGE_VISION_LOCAL_CONFIRMED" not in facts


def test_mono_engine_name_does_not_force_past_budget():
    """Latency: insured_name mono-engine E2 must not wipe DOC_BUDGET_SKIP."""
    row = {
        "field": "insured_name",
        "cascade": {"accepted": False, "value": "SMITH JOHN"},
        "candidates": [{"engine": "paddleocr", "value": "SMITH JOHN"}],
        "gap_class": "",
    }
    assert name_force_despite_budget(row) is False
    assert force_cloud_despite_budget("insured_name", row) is False


def test_patient_name_mono_engine_still_forces_past_budget():
    """Box 2 patient_name must not be budget-skipped (false HITL on garbled OCR)."""
    row = {
        "field": "patient_name",
        "cascade": {"accepted": False, "value": "CHANAUICNI ARUA. M"},
        "candidates": [{"engine": "rapidocr", "value": "CHANAUICNI ARUA. M"}],
        "gap_class": "",
    }
    assert name_force_despite_budget(row) is True
    assert force_cloud_despite_budget("patient_name", row) is True


def test_name_engine_conflict_forces_past_budget():
    row = {
        "field": "patient_name",
        "cascade": {"accepted": True, "value": "SMITH JOHN"},
        "candidates": [
            {"engine": "paddleocr", "value": "SMITH JOHN"},
            {"engine": "rapidocr", "value": "SMYTH JOHN"},
        ],
        "gap_class": "",
    }
    assert name_force_despite_budget(row) is True
    assert force_cloud_despite_budget("patient_name", row) is True
