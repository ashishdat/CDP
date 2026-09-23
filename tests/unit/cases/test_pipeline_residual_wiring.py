"""Deep residual-wiring tests — Independent-100 DJJM regression class."""

from __future__ import annotations

import pytest

from packages.extraction_recovery.cloud_stop_ladder import should_skip_all_cloud
from packages.extraction_recovery.gpt4o_crop_residual import (
    charge_needs_gpt4o,
    id_needs_gpt4o,
    maybe_attach_gpt4o_crop_to_field_row,
)
from packages.extraction_recovery.pipeline_contract import run_all_contracts


@pytest.fixture(autouse=True)
def _ladder_on(monkeypatch):
    monkeypatch.setenv("CDP_CLOUD_STOP_LADDER", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_ACCEPT", "1")


def test_pipeline_contracts():
    passed = run_all_contracts()
    assert len(passed) == 6


def test_djjm040_place_shift_not_locals_settled():
    """Box28 251 vs line 2.51 must not skip cloud."""
    cands = [
        {"engine": "paddleocr", "value": "251.00"},
        {"engine": "rapidocr", "value": "251.00"},
    ]
    row = {
        "field": "total_charge",
        "candidates": cands,
        "observed_line_charges": ["2.51"],
        "cascade": {"accepted": True, "value": "251.00"},
        "ocr_region": [100, 200, 300, 250],
    }
    assert should_skip_all_cloud("total_charge", row) is False
    assert (
        charge_needs_gpt4o(
            local_accepted=True,
            azure_di_shaped=False,
            candidates=cands,
            observed_line_charges=["2.51"],
        )
        is True
    )


def test_djjm037_zero_lines_not_locals_settled():
    cands = [
        {"engine": "paddleocr", "value": "125.00"},
        {"engine": "rapidocr", "value": "125.00"},
    ]
    row = {
        "field": "total_charge",
        "candidates": cands,
        "observed_line_charges": [],
        "cascade": {"accepted": True, "value": "125.00"},
    }
    assert should_skip_all_cloud("total_charge", row) is False
    assert (
        charge_needs_gpt4o(
            local_accepted=True,
            azure_di_shaped=False,
            candidates=cands,
            observed_line_charges=[],
        )
        is True
    )


def test_djjm039_short_padded_id_needs_vision_when_cascade_accepted():
    value = "00000259054"
    cands = [{"engine": "paddleocr", "value": value}]
    assert id_needs_gpt4o(value, accepted=True, candidates=cands) is True
    row = {
        "field": "insured_id_number",
        "candidates": cands,
        "cascade": {"accepted": True, "value": value},
    }
    assert should_skip_all_cloud("insured_id_number", row) is False


def test_maybe_attach_does_not_stamp_locals_settled_on_zero_line_charge(monkeypatch):
    """Nested should_skip_all_cloud(row) must honor observed_line_charges stamp."""
    from PIL import Image

    # Force residual disabled so we only test the skip gate, not network.
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "0")
    img = Image.new("L", (400, 400), 255)
    row = {
        "field": "total_charge",
        "candidates": [
            {"engine": "paddleocr", "value": "70.00"},
            {"engine": "rapidocr", "value": "70.00"},
        ],
        "observed_line_charges": [],
        "cascade": {"accepted": True, "value": "70.00"},
        "ocr_region": [10, 10, 100, 40],
    }
    # With residual off, maybe_attach returns early after gated checks —
    # enable residual but mock run to abstain; still must not LOCALS_SETTLED-skip.
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")

    def _fake_needs(**kwargs):
        return True

    monkeypatch.setattr(
        "packages.extraction_recovery.gpt4o_crop_residual.charge_needs_gpt4o",
        _fake_needs,
    )

    class _Eng:
        def recognize(self, **kwargs):
            from packages.extraction_recovery.gpt4o_crop_residual import (
                Gpt4oCropResidualResult,
            )

            return Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value=None,
                raw_value=None,
                shaped=False,
                insufficient_evidence=True,
                reason="ABSTAIN",
                engine="anthropic_claude_crop",
                confidence=None,
                validation_results=(),
            )

    out = maybe_attach_gpt4o_crop_to_field_row(row, image=img, engine=_Eng())
    skip = (out.get("cloud_stop_ladder") or {}).get("skipped")
    assert skip != "LOCALS_SETTLED"


def test_agreeing_box28_with_matching_lines_still_settles():
    cands = [
        {"engine": "paddleocr", "value": "251.00"},
        {"engine": "rapidocr", "value": "251.00"},
    ]
    row = {
        "field": "total_charge",
        "candidates": cands,
        "observed_line_charges": ["100.00", "151.00"],
    }
    assert should_skip_all_cloud("total_charge", row) is True
    assert (
        charge_needs_gpt4o(
            local_accepted=True,
            azure_di_shaped=False,
            candidates=cands,
            observed_line_charges=["100.00", "151.00"],
        )
        is False
    )


def test_dual_engine_short_padded_id_settles_without_vision():
    """paddle+rapid on same padded canon may skip cloud (latency path)."""
    value = "0000007267"
    cands = [
        {"engine": "paddleocr", "value": value},
        {"engine": "rapidocr", "value": value},
    ]
    assert id_needs_gpt4o(value, accepted=True, candidates=cands) is False
    row = {
        "field": "insured_id_number",
        "candidates": cands,
        "cascade": {"accepted": True, "value": value},
    }
    assert should_skip_all_cloud("insured_id_number", row) is True


def test_charge_azure_di_respects_empty_line_stamp(monkeypatch):
    """DI attach must not LOCALS_SETTLED-skip when row stamp is []."""
    from PIL import Image

    from packages.extraction_recovery.charge_azure_di_residual import (
        maybe_attach_charge_azure_di_to_field_row,
    )

    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    img = Image.new("L", (200, 80), 255)
    row = {
        "field": "total_charge",
        "candidates": [
            {"engine": "paddleocr", "value": "90.00"},
            {"engine": "rapidocr", "value": "90.00"},
        ],
        "observed_line_charges": [],
        "cascade": {"accepted": True, "value": "90.00"},
        "ocr_region": [10, 10, 100, 40],
    }

    class _Eng:
        def recognize_crop(self, crop, field_name: str):
            from packages.extraction_recovery.charge_azure_di_residual import (
                ChargeAzureDiResidualResult,
            )

            return ChargeAzureDiResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value=None,
                raw_value=None,
                currency_shaped=False,
                reason="ABSTAIN",
            )

    # If stamp ignored, attach returns early with LOCALS_SETTLED and never calls engine.
    out = maybe_attach_charge_azure_di_to_field_row(
        row, image=img, gap_class="CHARGE_LOCAL_EXHAUSTED", engine=_Eng()
    )
    skip = (out.get("cloud_stop_ladder") or {}).get("skipped")
    assert skip != "LOCALS_SETTLED"
    assert (out.get("azure_di_residual") or {}).get("attempted") is True
