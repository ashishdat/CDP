"""Unit tests for residual taxonomy + product gate + accept policy."""

from __future__ import annotations

from packages.evaluation.agent_gt_score import exact_match
from packages.extraction_recovery.residual_taxonomy import (
    ResidualClass,
    classify_hitl_residual,
)
from packages.product_gates.accuracy_accept_policy import (
    evaluate_insured_name_accept,
    filter_auto_fields,
)
from packages.product_gates.similar_sample_gate import evaluate_similar_sample_gate


def test_spouse_empty_blockers_are_rel_conflict():
    assert (
        classify_hitl_residual(
            hitl_track="FIELD_INK",
            critical_blockers=[],
            relationship="SPOUSE",
        )
        is ResidualClass.REL_CONFLICT
    )


def test_charge_scale_rival_is_policy_hold():
    assert (
        classify_hitl_residual(
            hitl_track="FIELD_INK",
            critical_blockers=["total_charge"],
            reason_codes=["CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL"],
        )
        is ResidualClass.POLICY_HOLD
    )


def test_empty_dob_is_ink_absent():
    assert (
        classify_hitl_residual(
            hitl_track="FIELD_INK",
            critical_blockers=["patient_dob"],
            reason_codes=["NO_NONEMPTY_CANDIDATE"],
        )
        is ResidualClass.INK_ABSENT
    )


def test_unstructured_missing_charge_is_ink_absent():
    assert (
        classify_hitl_residual(
            hitl_track="UNSTRUCTURED_DI",
            critical_blockers=["total_charge"],
        )
        is ResidualClass.INK_ABSENT
    )


def test_product_gate_fails_below_97_without_inventing():
    # 809/841 ≈ 0.962 — below 0.97
    rows = {}
    for i in range(809):
        rows[f"stp_{i}"] = {"disposition": "TRUE_STP", "claim_id": f"stp_{i}"}
    for i in range(32):
        rows[f"hitl_{i}"] = {
            "disposition": "HITL",
            "claim_id": f"hitl_{i}",
            "hitl_track": "FIELD_INK",
            "critical_blockers": ["total_charge"],
            "reason_codes": ["CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL"],
        }
    for i in range(159):
        rows[f"reg_{i}"] = {"disposition": "REGISTRATION_FAILED", "claim_id": f"reg_{i}"}
    result = evaluate_similar_sample_gate(rows, allow_incomplete_gt=True)
    assert result.claim_pages == 841
    assert result.claim_page_stp == 0.962
    assert result.pass_gate is False
    assert any("CLAIM_PAGE_STP_BELOW_TARGET" in r for r in result.reasons)
    assert result.residual_counts.get("POLICY_HOLD", 0) == 32


def test_product_gate_passes_at_97_with_fa_incomplete_allowed():
    rows = {}
    for i in range(816):
        rows[f"stp_{i}"] = {"disposition": "TRUE_STP", "claim_id": f"stp_{i}"}
    for i in range(25):
        rows[f"hitl_{i}"] = {
            "disposition": "HITL",
            "claim_id": f"hitl_{i}",
            "hitl_track": "FIELD_INK",
            "critical_blockers": ["patient_dob"],
            "reason_codes": ["NO_NONEMPTY_CANDIDATE"],
        }
    result = evaluate_similar_sample_gate(rows, allow_incomplete_gt=True)
    assert result.claim_page_stp >= 0.97
    assert result.pass_gate is True


def test_accept_policy_rejects_placeholder_insured_name():
    verdict = evaluate_insured_name_accept("SNASLLASTNANE, PNSTNANE")
    assert verdict.allow_auto is False
    assert "PLACEHOLDER_INSURED_NAME" in verdict.reason_codes


def test_accept_policy_rejects_unresolved_same():
    verdict = evaluate_insured_name_accept("SAME")
    assert verdict.allow_auto is False
    assert "UNRESOLVED_SAME_INSURED_NAME" in verdict.reason_codes


def test_accept_policy_rejects_truncated_self_name():
    verdict = evaluate_insured_name_accept(
        "GOLD",
        patient_name="GOLD, CHRISTINA",
        relationship="Self",
    )
    assert verdict.allow_auto is False
    assert "TRUNCATED_INSURED_NAME_VS_PATIENT" in verdict.reason_codes


def test_filter_auto_fields_keeps_clean_values():
    kept, blocked = filter_auto_fields(
        {
            "patient_name": "THOMAS DARLENE",
            "insured_name": "THOMAS DARLENE",
            "insured_id_number": "0000374350",
            "total_charge": "1160.00",
        }
    )
    assert blocked == ()
    assert "insured_name" in kept


def test_exact_match_leading_zeros_and_middle_initial():
    assert exact_match("insured_id_number", "00000259054", "259054")
    assert exact_match("patient_name", "GAVIN. ROBERT, M", "GAVIN ROBERT")
    assert exact_match("patient_dob", "1998-10-31", "10/31/1998")
    assert exact_match(
        "insured_name",
        "SAME",
        "SAME",
        patient_name="WILLIAMS JOYCE",
    )
    assert exact_match(
        "insured_name",
        "WILLIAMS JOYCE",
        "SAME",
        patient_name="WILLIAMS JOYCE",
    )
