"""Pipeline residual-wiring contract — catch stop-ladder / ID gate regressions.

Independent-100 regressions (DJJM.*):
  - dual-local Box28 + 0 lines stamped LOCALS_SETTLED → MISSING_E4
  - Box28 251 vs line 2.51 stamped LOCALS_SETTLED → place-shift HITL
  - short-padded ID cascade-accepted → no vision → SHORT_PADDED HITL

These helpers + tests fail closed when nested residual paths ignore line
context or padded-ID corroboration requirements.
"""

from __future__ import annotations

from typing import Any, Mapping


def assert_charge_zero_lines_needs_cloud(
    candidates: list[Mapping[str, Any]] | None = None,
) -> None:
    from packages.extraction_recovery.cloud_stop_ladder import (
        charge_locals_settled,
        should_skip_all_cloud,
    )
    from packages.extraction_recovery.gpt4o_crop_residual import charge_needs_gpt4o

    cands = candidates or [
        {"engine": "paddleocr", "value": "125.00"},
        {"engine": "rapidocr", "value": "125.00"},
    ]
    assert charge_locals_settled(cands, observed_line_charges=[]) is False
    row = {"field": "total_charge", "candidates": cands, "observed_line_charges": []}
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


def assert_charge_place_shift_needs_cloud(
    candidates: list[Mapping[str, Any]] | None = None,
    line: str = "2.51",
) -> None:
    from packages.extraction_recovery.cloud_stop_ladder import (
        charge_locals_settled,
        should_skip_all_cloud,
    )
    from packages.extraction_recovery.gpt4o_crop_residual import charge_needs_gpt4o

    cands = candidates or [
        {"engine": "paddleocr", "value": "251.00"},
        {"engine": "rapidocr", "value": "251.00"},
    ]
    lines = [line]
    assert charge_locals_settled(cands, observed_line_charges=lines) is False
    row = {
        "field": "total_charge",
        "candidates": cands,
        "observed_line_charges": lines,
        "cascade": {"accepted": True, "value": "251.00"},
    }
    assert should_skip_all_cloud("total_charge", row) is False
    assert (
        charge_needs_gpt4o(
            local_accepted=True,
            azure_di_shaped=False,
            candidates=cands,
            observed_line_charges=lines,
        )
        is True
    )


def assert_short_padded_id_needs_vision(value: str = "00000259054") -> None:
    from packages.extraction_recovery.cloud_stop_ladder import should_skip_all_cloud
    from packages.extraction_recovery.gpt4o_crop_residual import (
        id_local_already_settled,
        id_local_needs_gpt4o,
        id_needs_gpt4o,
    )

    cands = [{"engine": "paddleocr", "value": value}]
    assert id_local_already_settled(cands) is False
    assert id_local_needs_gpt4o(value, accepted=True) is True
    assert id_needs_gpt4o(value, accepted=True, candidates=cands) is True
    row = {
        "field": "insured_id_number",
        "candidates": cands,
        "cascade": {"accepted": True, "value": value},
    }
    assert should_skip_all_cloud("insured_id_number", row) is False


def assert_dual_engine_padded_id_may_settle(value: str = "0000007267") -> None:
    """Multi-family padded agreement is allowed to skip cloud (latency)."""
    from packages.extraction_recovery.cloud_stop_ladder import should_skip_all_cloud
    from packages.extraction_recovery.gpt4o_crop_residual import id_needs_gpt4o

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


def assert_nested_skip_respects_row_line_stamp() -> None:
    """gpt4o/DI helpers call should_skip_all_cloud(row) without explicit lines."""
    from packages.extraction_recovery.cloud_stop_ladder import should_skip_all_cloud

    cands = [
        {"engine": "paddleocr", "value": "578.00"},
        {"engine": "rapidocr", "value": "578.00"},
    ]
    # Without stamp — legacy settle (dangerous if residual forgets lines).
    bare = {"field": "total_charge", "candidates": cands}
    assert should_skip_all_cloud("total_charge", bare) is True
    # With empty stamp — must NOT settle.
    stamped = {
        "field": "total_charge",
        "candidates": cands,
        "observed_line_charges": [],
    }
    assert should_skip_all_cloud("total_charge", stamped) is False


def assert_di_place_shift_rival_stays_hitl() -> None:
    """DJKN.005: DI+Claude 200 must not AUTO beside paddle 2001."""
    from packages.candidate_reconciliation import Decision, EvidenceReconciler
    from packages.criticality import CriticalityLevel
    from packages.domain.common import BoundingBox
    from packages.ocr.contracts import OCRCandidate

    def _c(value: str, engine: str, conf: float = 0.99) -> OCRCandidate:
        return OCRCandidate(
            value=value,
            raw_value=value,
            engine=engine,
            model_name=engine,
            model_version="1",
            preprocessing_variant="original",
            raw_confidence=conf,
            calibrated_confidence=None,
            bounding_box=BoundingBox(
                x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100
            ),
            latency_ms=1,
            evidence_reference=None,
        )

    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _c("200.00", "azure_document_intelligence_read", 0.99),
            _c("200.00", "anthropic_claude_crop", 0.98),
            _c("2001.00", "paddleocr", 0.97),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CHARGE_DI_LOCAL_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"200", "200.00"},
    )
    assert result.decision != Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes


def run_all_contracts() -> list[str]:
    """Return names of contracts that passed (raises on first failure)."""
    assert_charge_zero_lines_needs_cloud()
    assert_charge_place_shift_needs_cloud()
    assert_short_padded_id_needs_vision()
    assert_dual_engine_padded_id_may_settle()
    assert_nested_skip_respects_row_line_stamp()
    assert_di_place_shift_rival_stays_hitl()
    return [
        "charge_zero_lines_needs_cloud",
        "charge_place_shift_needs_cloud",
        "short_padded_id_needs_vision",
        "dual_engine_padded_id_may_settle",
        "nested_skip_respects_row_line_stamp",
        "di_place_shift_rival_stays_hitl",
    ]
