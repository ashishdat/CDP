"""Per-field reader: local OCR, then the one allowed model."""

from packages.claim_evidence.line_sum_authority import line_sum_auto_eligible
from packages.extraction_recovery.field_reader_policy import (
    azure_di_on_path,
    model_may_supersede,
    reader_for,
)
from scripts.ocr_from_geometry import _confirm_sole_charge_line_with_claude


def test_each_critical_field_has_one_reader():
    dob = reader_for("patient_dob")
    assert dob is not None
    assert dob.local_residual == "trocr"
    assert dob.model == "claude"
    assert dob.model_may_supersede is False
    assert reader_for("date_of_birth").local_residual == "trocr"

    assert model_may_supersede("patient_name") is True
    assert model_may_supersede("insured_name") is True
    assert model_may_supersede("insured_id_number") is False
    assert reader_for("member_id").model == "claude"

    charge = reader_for("total_charge")
    assert charge.local_ocr == ("paddleocr", "rapidocr")
    assert charge.local_residual == "tesseract_digits"
    assert charge.model == "claude"
    assert model_may_supersede("charges") is False
    assert model_may_supersede("charge_amount") is False

    for field in ("patient_dob", "patient_name", "insured_id_number", "total_charge", "charges"):
        assert azure_di_on_path(field) is False


def test_sole_charge_line_claude_confirms_local_amount(monkeypatch):
    """Legacy always-corroborate path (cost-safe off)."""
    monkeypatch.setenv("CDP_SOLE_LINE_CLAUDE_COST_SAFE", "0")

    def _crop(image, bbox, *, prior_candidates=None):
        del image, bbox, prior_candidates
        return (
            "200.00",
            "200.00",
            [{"engine": "azure_gpt4o_crop", "value": "200.00", "source_crop_id": "c3"}],
            "CLAUDE_OK",
        )

    monkeypatch.setattr(
        "scripts.ocr_from_geometry._maybe_gpt4o_charge_crop",
        _crop,
    )
    lines = [
        {
            "charges": "200.00",
            "raw_charges": "200",
            "canonical_region": (10, 20, 30, 40),
            "candidates": [
                {"engine": "paddleocr", "value": "200.00", "source_crop_id": "c1"},
                {"engine": "rapidocr", "value": "200.00", "source_crop_id": "c2"},
            ],
            "attempts": [
                {"engine": "azure_gpt4o_crop", "reason": "CHARGE_GPT4O_SKIPPED_DUAL_LOCAL"}
            ],
            "router_reason": "DUAL_LOCAL",
        }
    ]
    out = _confirm_sole_charge_line_with_claude(None, lines)
    assert out[0]["charges"] == "200.00"
    assert "CHARGE_CLAUDE_CONFIRMS_LOCAL" in out[0]["router_reason"]
    ok, reason = line_sum_auto_eligible(out)
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"


def test_sole_line_cost_safe_defers_without_box28(monkeypatch):
    monkeypatch.setenv("CDP_SOLE_LINE_CLAUDE_COST_SAFE", "1")
    called = {"n": 0}

    def _crop(image, bbox, *, prior_candidates=None):
        del image, bbox, prior_candidates
        called["n"] += 1
        return "200.00", "200", [{"engine": "azure_gpt4o_crop", "value": "200.00"}], "X"

    monkeypatch.setattr("scripts.ocr_from_geometry._maybe_gpt4o_charge_crop", _crop)
    lines = [
        {
            "charges": "200.00",
            "raw_charges": "200",
            "canonical_region": (10, 20, 30, 40),
            "candidates": [
                {"engine": "paddleocr", "value": "200.00"},
                {"engine": "rapidocr", "value": "200.00"},
            ],
            "attempts": [
                {"engine": "azure_gpt4o_crop", "reason": "CHARGE_GPT4O_SKIPPED_DUAL_LOCAL"}
            ],
            "router_reason": "DUAL_LOCAL",
        }
    ]
    out = _confirm_sole_charge_line_with_claude(None, lines, box28_row=None)
    assert called["n"] == 0
    reasons = [a.get("reason") for a in out[0]["attempts"]]
    assert "CHARGE_GPT4O_DEFERRED_SOLE_LINE" in reasons


def test_sole_line_cost_safe_skips_when_box28_di_settled(monkeypatch):
    monkeypatch.setenv("CDP_SOLE_LINE_CLAUDE_COST_SAFE", "1")
    called = {"n": 0}

    def _crop(image, bbox, *, prior_candidates=None):
        del image, bbox, prior_candidates
        called["n"] += 1
        return "200.00", "200", [{"engine": "azure_gpt4o_crop", "value": "200.00"}], "X"

    monkeypatch.setattr("scripts.ocr_from_geometry._maybe_gpt4o_charge_crop", _crop)
    lines = [
        {
            "charges": "200.00",
            "raw_charges": "200",
            "canonical_region": (10, 20, 30, 40),
            "candidates": [
                {"engine": "paddleocr", "value": "200.00"},
                {"engine": "rapidocr", "value": "200.00"},
            ],
            "attempts": [
                {"engine": "azure_gpt4o_crop", "reason": "CHARGE_GPT4O_SKIPPED_DUAL_LOCAL"},
                {"engine": "azure_gpt4o_crop", "reason": "CHARGE_GPT4O_DEFERRED_SOLE_LINE"},
            ],
            "router_reason": "DUAL_LOCAL",
        }
    ]
    box28 = {
        "field": "total_charge",
        "candidates": [
            {"engine": "paddleocr", "value": "200.00"},
            {"engine": "rapidocr", "value": "200.00"},
            {"engine": "azure_document_intelligence_read", "value": "200.00"},
        ],
        "azure_di_residual": {
            "currency_shaped": True,
            "review_only": False,
            "value": "200.00",
        },
        "observed_line_charges": ["200.00"],
    }
    out = _confirm_sole_charge_line_with_claude(None, lines, box28_row=box28)
    assert called["n"] == 0
    reasons = [a.get("reason") for a in out[0]["attempts"]]
    assert "CHARGE_GPT4O_SKIPPED_BOX28_SETTLED" in reasons


def test_sole_line_cost_safe_calls_claude_when_box28_empty(monkeypatch):
    monkeypatch.setenv("CDP_SOLE_LINE_CLAUDE_COST_SAFE", "1")

    def _crop(image, bbox, *, prior_candidates=None):
        del image, bbox, prior_candidates
        return (
            "200.00",
            "200.00",
            [{"engine": "azure_gpt4o_crop", "value": "200.00", "source_crop_id": "c3"}],
            "CLAUDE_OK",
        )

    monkeypatch.setattr("scripts.ocr_from_geometry._maybe_gpt4o_charge_crop", _crop)
    lines = [
        {
            "charges": "200.00",
            "raw_charges": "200",
            "canonical_region": (10, 20, 30, 40),
            "candidates": [
                {"engine": "paddleocr", "value": "200.00", "source_crop_id": "c1"},
                {"engine": "rapidocr", "value": "200.00", "source_crop_id": "c2"},
            ],
            "attempts": [
                {"engine": "azure_gpt4o_crop", "reason": "CHARGE_GPT4O_SKIPPED_DUAL_LOCAL"},
                {"engine": "azure_gpt4o_crop", "reason": "CHARGE_GPT4O_DEFERRED_SOLE_LINE"},
            ],
            "router_reason": "DUAL_LOCAL",
        }
    ]
    box28 = {
        "field": "total_charge",
        "candidates": [],
        "cascade": {"accepted": False, "value": ""},
        "observed_line_charges": ["200.00"],
    }
    out = _confirm_sole_charge_line_with_claude(None, lines, box28_row=box28)
    assert "CHARGE_CLAUDE_CONFIRMS_LOCAL" in out[0]["router_reason"]
    ok, reason = line_sum_auto_eligible(out)
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"


def test_claude_cannot_supersede_a_charge(monkeypatch):
    monkeypatch.setenv("CDP_SOLE_LINE_CLAUDE_COST_SAFE", "0")

    def _crop(image, bbox, *, prior_candidates=None):
        del image, bbox, prior_candidates
        return (
            "131.00",
            "131",
            [{"engine": "azure_gpt4o_crop", "value": "131.00"}],
            "CLAUDE_OTHER",
        )

    monkeypatch.setattr(
        "scripts.ocr_from_geometry._maybe_gpt4o_charge_crop",
        _crop,
    )
    lines = [
        {
            "charges": "13.00",
            "raw_charges": "13",
            "canonical_region": (10, 20, 30, 40),
            "candidates": [
                {"engine": "paddleocr", "value": "13.00"},
                {"engine": "rapidocr", "value": "13.00"},
            ],
            "attempts": [
                {"engine": "azure_gpt4o_crop", "reason": "CHARGE_GPT4O_SKIPPED_DUAL_LOCAL"}
            ],
            "router_reason": "DUAL_LOCAL",
        }
    ]
    out = _confirm_sole_charge_line_with_claude(None, lines)
    assert out[0]["charges"] == "13.00"
    assert "CHARGE_CLAUDE_SUPERSEDE_BLOCKED" in out[0]["router_reason"]
    ok, reason = line_sum_auto_eligible(out)
    assert not ok and reason == "SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28"


def test_multi_line_dual_local_does_not_call_claude(monkeypatch):
    called = {"n": 0}

    def _crop(image, bbox, *, prior_candidates=None):
        del image, bbox, prior_candidates
        called["n"] += 1
        return "200.00", "200", [{"engine": "azure_gpt4o_crop", "value": "200.00"}], "X"

    monkeypatch.setattr(
        "scripts.ocr_from_geometry._maybe_gpt4o_charge_crop",
        _crop,
    )
    lines = [
        {
            "charges": "200.00",
            "canonical_region": (1, 2, 3, 4),
            "candidates": [],
            "attempts": [{"reason": "CHARGE_GPT4O_SKIPPED_DUAL_LOCAL"}],
        },
        {
            "charges": "50.00",
            "canonical_region": (1, 5, 3, 8),
            "candidates": [],
            "attempts": [{"reason": "CHARGE_GPT4O_SKIPPED_DUAL_LOCAL"}],
        },
    ]
    _confirm_sole_charge_line_with_claude(None, lines)
    assert called["n"] == 0
