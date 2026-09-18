"""Unit tests for registration telemetry fast path and name confirm confidence."""

from __future__ import annotations

from scripts.ocr_from_geometry import _name_confirm_confidence
from workers.page_detection.registration_telemetry import verbose_registration_telemetry


def test_verbose_telemetry_defaults_off(monkeypatch):
    monkeypatch.delenv("CDP_REGISTRATION_VERBOSE_TELEMETRY", raising=False)
    assert verbose_registration_telemetry() is False


def test_verbose_telemetry_opt_in(monkeypatch):
    monkeypatch.setenv("CDP_REGISTRATION_VERBOSE_TELEMETRY", "1")
    assert verbose_registration_telemetry() is True


def test_name_confirm_ignores_weak_short_fragment():
    attempts = [
        {
            "engine": "paddleocr",
            "observation": {
                "lines": [
                    {"text": "DEPONTE", "confidence": 0.996},
                    {"text": "DESIRAE", "confidence": 0.997},
                    {"text": "CL", "confidence": 0.62},
                ]
            },
        }
    ]
    candidates = [{"value": "DEPONTE DESIRAE CL", "raw_confidence": 0.872}]
    conf = _name_confirm_confidence(attempts, candidates)
    assert conf >= 0.88
    assert conf > candidates[0]["raw_confidence"]


def test_name_confirm_falls_back_to_candidate_confidence():
    attempts = [{"engine": "paddleocr", "observation": {"lines": []}}]
    candidates = [{"value": "DATST EY", "raw_confidence": 0.75}]
    assert _name_confirm_confidence(attempts, candidates) == 0.75


def test_stp_critical_skips_non_blocking_diagnosis_and_tax():
    import os

    from scripts.ocr_from_geometry import _STP_CRITICAL_FIELDS, _field_in_scope

    os.environ["CDP_OCR_FIELD_SCOPE"] = "stp_critical"
    assert "diagnosis_codes" not in _STP_CRITICAL_FIELDS
    assert "federal_tax_id" not in _STP_CRITICAL_FIELDS
    assert _field_in_scope("patient_name") is True
    assert _field_in_scope("diagnosis_codes") is False
    assert _field_in_scope("federal_tax_id") is False


def test_shared_trocr_adapter_is_singleton():
    from workers.unstructured_extraction.trocr_adapter import get_shared_trocr_adapter

    a = get_shared_trocr_adapter(model_name="microsoft/trocr-base-handwritten", device="cpu")
    b = get_shared_trocr_adapter(model_name="microsoft/trocr-base-handwritten", device="cpu")
    assert a is b


def test_dob_planner_does_not_blanket_match_calibration_gap():
    from packages.tool_escalation import EscalationTool, plan_field_escalation

    decision = plan_field_escalation(
        gap_class="CALIBRATION_HITL",
        field_name="patient_dob",
        trocr_attempted=False,
    )
    assert decision.tool != EscalationTool.TROCR
