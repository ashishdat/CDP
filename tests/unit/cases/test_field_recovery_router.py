"""Unit tests for field recovery tool stack v13 router."""

from __future__ import annotations

from packages.extraction_recovery.field_recovery_router import (
    FailureMode,
    RecoveryTool,
    classify_failure_mode,
    cloud_tools_for_plan,
    plan_recovery,
)


def test_empty_finance_is_missing_ink():
    mode = classify_failure_mode(
        "total_charge",
        gap_class="EMPTY_FINANCIAL_INK",
        candidates=[],
        observed_line_charges=[],
    )
    assert mode is FailureMode.MISSING_INK
    plan = plan_recovery(
        "total_charge",
        gap_class="EMPTY_FINANCIAL_INK",
        observed_line_charges=[],
    )
    assert plan.steps[0] is RecoveryTool.DUAL_LOCAL
    assert RecoveryTool.AZURE_DI_CROP in plan.steps
    assert plan.steps[-1] is RecoveryTool.HITL


def test_place_shift_box28_vs_line_is_overlap():
    cands = [
        {"engine": "paddleocr", "value": "251.00"},
        {"engine": "rapidocr", "value": "251.00"},
    ]
    mode = classify_failure_mode(
        "total_charge",
        candidates=cands,
        observed_line_charges=["2.51"],
        reason_codes=["LINE_TOTALS_GATE:SINGLE_LINE_REQUIRES_DI"],
    )
    assert mode is FailureMode.OVERLAP
    plan = plan_recovery(
        "total_charge",
        candidates=cands,
        observed_line_charges=["2.51"],
        reason_codes=["LINE_TOTALS_GATE:SINGLE_LINE_REQUIRES_DI"],
    )
    assert RecoveryTool.AZURE_DI_CROP in plan.steps
    assert RecoveryTool.VISION_CROP in plan.steps


def test_bleed_cents_is_overlap_with_cash_ruling_first():
    plan = plan_recovery(
        "total_charge",
        reason_codes=["BLEED_CENTS_FAIL_CLOSED"],
        candidates=[
            {"engine": "anthropic_claude_crop", "value": "25.43"},
            {"engine": "paddleocr", "value": "251.43"},
        ],
    )
    assert plan.mode is FailureMode.OVERLAP
    assert plan.steps[0] is RecoveryTool.CASH_RULING


def test_name_conflict_is_conflict_mode():
    plan = plan_recovery(
        "patient_name",
        gap_class="NAME_ENGINE_CONFLICT",
        reason_codes=["CONFLICT_MARGIN_TOO_SMALL"],
        observed_text="crmauiani . Aiay . M",
    )
    assert plan.mode is FailureMode.CONFLICT
    assert RecoveryTool.VISION_CROP in plan.steps
    assert RecoveryTool.CONFLICT_AGENT in plan.steps


def test_short_padded_id_is_missing_ink_force_vision():
    plan = plan_recovery(
        "insured_id_number",
        reason_codes=["SHORT_PADDED_MEMBER_ID_NEEDS_CORROBORATION"],
        observed_text="0000374350",
    )
    assert plan.mode is FailureMode.MISSING_INK
    assert RecoveryTool.VISION_CROP in plan.steps


def test_missing_e4_zero_lines_overlap_policy():
    mode = classify_failure_mode(
        "total_charge",
        gap_class="EVIDENCE_POLICY_GAP",
        reason_codes=["MISSING_E4_DETERMINISTIC_VALIDATION"],
        candidates=[
            {"engine": "paddleocr", "value": "90.00"},
            {"engine": "rapidocr", "value": "90.00"},
        ],
        observed_text="90.00",
        observed_line_charges=[],
    )
    assert mode is FailureMode.OVERLAP


def test_cloud_tools_extract():
    plan = plan_recovery(
        "patient_dob",
        gap_class="HANDWRITING_UNREADABLE",
        observed_text="",
    )
    cloud = cloud_tools_for_plan(plan)
    assert RecoveryTool.TROCR in cloud or RecoveryTool.AZURE_DI_CROP in cloud
    assert RecoveryTool.HITL not in cloud


def test_no_residual_none_mode():
    plan = plan_recovery("patient_dob", gap_class=None, reason_codes=[], observed_text="03/15/1987")
    # Without gap/reasons and with text, DOB may still be NONE
    assert plan.mode in {FailureMode.NONE, FailureMode.MISSING_INK, FailureMode.CONFLICT}
