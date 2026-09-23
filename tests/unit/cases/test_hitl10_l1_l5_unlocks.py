"""HITL-10 L1–L5 precision-safe unlocks (Independent-100 v13b remaining)."""

from __future__ import annotations

from packages.candidate_reconciliation.contracts import Decision
from packages.candidate_reconciliation.reconciler import EvidenceReconciler
from packages.claim_evidence.builder import ClaimEvidenceBuilder
from packages.claim_evidence.charge_total_authority import (
    authorize_conflict_agent_charge,
)
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence.builder import build_evidence_bundle
from packages.ocr.contracts import OCRCandidate


def _cand(
    engine: str,
    value: str,
    conf: float = 0.95,
    *,
    raw_value: str | None = None,
) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=raw_value if raw_value is not None else value,
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


def test_l1_agent_lines_not_digit_drop_upgraded_to_box28():
    """DJJM.040: agent LINES 2.51 must not become fuller Box28 251."""
    result = ClaimEvidenceBuilder.load().build(
        claim_id="DJJM.040",
        document_family="CMS1500",
        claim_values={
            "total_charge": "2.51",
            "_financial_conflict_agent": {
                "side": "LINES",
                "value": "2.51",
                "reason": "CONFLICT_AGENT_CENTS_COLUMN_PREFER_LINES",
            },
            "_box28_field_payload": {
                "candidates": [
                    {"engine": "paddleocr", "value": "251.00"},
                    {"engine": "rapidocr", "value": "2.51"},
                    {"engine": "azure_document_intelligence_read", "value": "251.00"},
                ]
            },
        },
        service_lines=[{"charges": "2.51"}],
    )
    confirmed = [
        i
        for i in result.evidence_items
        if i.evidence_type == "CLAIM_TOTAL_CONFIRMED"
    ]
    assert confirmed
    assert all(str(i.value) == "2.51" for i in confirmed)
    reasons = {(i.metadata or {}).get("reason") for i in confirmed}
    assert reasons & {
        "LINE_SUM_CORROBORATES_CONFLICT_PICK",
        "DUAL_OPEN_SOURCE_CHARGE_AGREEMENT",
    }
    assert not any(
        i.evidence_type == "FINANCIAL_CONFLICT_HITL" for i in result.evidence_items
    )


def test_l2_underread_scrap_does_not_block_di_local_e4():
    """EJG7.009: paddle 20 scrap beside DI+Claude 200 still mints E4."""
    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("azure_document_intelligence_read", "200.00"),
            _cand("anthropic_claude_crop", "200.00"),
            _cand("paddleocr", "20.00"),
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
    assert "CHARGE_DI_LOCAL_CONFIRMED" in facts


def test_l2_inflated_rival_still_blocks_vision_local_e4():
    """DJKN.005-class: fuller 2001 beside 200 still blocks E4."""
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


def test_l2_vision_local_clears_non_place_shift_di_rival():
    """DJKH.023: Claude+local 70 clears DI 100 when DI raw embeds both tokens."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _cand("anthropic_claude_crop", "70.00"),
            _cand("paddleocr", "70.00"),
            _cand(
                "azure_document_intelligence_read",
                "100.00",
                raw_value="J $ 70 100",
            ),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CHARGE_VISION_LOCAL_CONFIRMED",
            "MULTI_ENGINE_AGREEMENT",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"70", "70.00"},
    )
    assert result.selected_value == "70.00"
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_l2_underread_rival_cleared_when_vision_local_owns_fuller():
    """EJG7.007-class: DI 14 scrap beside Claude+local 140 is soup."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _cand("anthropic_claude_crop", "140.00"),
            _cand("paddleocr", "140.00"),
            _cand("azure_document_intelligence_read", "14.00"),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CHARGE_VISION_LOCAL_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"140", "140.00"},
    )
    assert result.selected_value == "140.00"
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_l3_vision_local_bleed_cents_not_fail_closed():
    """DJKH.030: Claude+local 251.43 vs DI 25143 is not BLEED_CENTS_FAIL_CLOSED."""
    auth, reason = authorize_conflict_agent_charge(
        "251.43",
        candidates=[
            {"engine": "anthropic_claude_crop", "value": "251.43"},
            {"engine": "paddleocr", "value": "251.43"},
            {"engine": "azure_document_intelligence_read", "value": "25143.00"},
        ],
    )
    assert auth == "251.43"
    assert reason == "VISION_LOCAL_PRINTED_BLEED_CENTS"

    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("anthropic_claude_crop", "251.43"),
            _cand("paddleocr", "251.43"),
            _cand("azure_document_intelligence_read", "25143.00"),
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

    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _cand("anthropic_claude_crop", "251.43"),
            _cand("paddleocr", "251.43"),
            _cand("azure_document_intelligence_read", "25143.00"),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CHARGE_VISION_LOCAL_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"251.43"},
    )
    assert result.selected_value == "251.43"
    assert "BLEED_CENTS_FAIL_CLOSED" not in result.rationale_codes
    assert result.decision == Decision.ACCEPT


def test_l4_exact_di_partner_authorizes_box28_over_single_line():
    """EJG7.005: agent BOX28 400 with DI+Claude exact; line 120 is not a veto."""
    auth, reason = authorize_conflict_agent_charge(
        "400.00",
        candidates=[
            {"engine": "azure_document_intelligence_read", "value": "400.00"},
            {"engine": "anthropic_claude_crop", "value": "400.00"},
            {"engine": "paddleocr", "value": "120.00"},
        ],
        service_lines=[{"charges": "120.00"}],
    )
    assert auth == "400.00"
    assert reason == "BOX28_DI_PARTNER_CONFIRMS_CONFLICT_PICK"

    result = ClaimEvidenceBuilder.load().build(
        claim_id="EJG7.005",
        document_family="CMS1500",
        claim_values={
            "total_charge": "400.00",
            "_financial_conflict_agent": {
                "side": "BOX28",
                "value": "400.00",
                "reason": "CONFLICT_AGENT_FINANCIAL_RESOLVED",
            },
            "_box28_field_payload": {
                "candidates": [
                    {"engine": "azure_document_intelligence_read", "value": "400.00"},
                    {"engine": "anthropic_claude_crop", "value": "400.00"},
                    {"engine": "paddleocr", "value": "120.00"},
                ]
            },
        },
        service_lines=[{"charges": "120.00"}],
    )
    assert any(
        i.evidence_type == "CLAIM_TOTAL_CONFIRMED"
        and str(i.value) == "400.00"
        and (i.metadata or {}).get("reason")
        == "BOX28_DI_PARTNER_CONFIRMS_CONFLICT_PICK"
        for i in result.evidence_items
    )


def test_l4_di_partner_not_upgraded_to_digit_drop_twin():
    """EJG7.005 live: DI+Claude 400 must not become rapid 4007 digit-drop fuller."""
    result = ClaimEvidenceBuilder.load().build(
        claim_id="EJG7.005-4007",
        document_family="CMS1500",
        claim_values={
            "total_charge": "400.00",
            "_financial_conflict_agent": {
                "side": "BOX28",
                "value": "400.00",
                "reason": "CONFLICT_AGENT_FINANCIAL_RESOLVED",
            },
            "_box28_field_payload": {
                "candidates": [
                    {"engine": "azure_document_intelligence_read", "value": "400.00"},
                    {"engine": "anthropic_claude_crop", "value": "400.00"},
                    {"engine": "rapidocr", "value": "4007.00"},
                ]
            },
        },
        service_lines=[{"charges": "120.00"}],
    )
    confirmed = [
        i
        for i in result.evidence_items
        if i.evidence_type == "CLAIM_TOTAL_CONFIRMED"
    ]
    assert confirmed
    assert all(str(i.value) == "400.00" for i in confirmed)
    assert all(
        (i.metadata or {}).get("reason") == "BOX28_DI_PARTNER_CONFIRMS_CONFLICT_PICK"
        for i in confirmed
    )


def test_l4_scale_twin_di_does_not_authorize_inflated_box28():
    """DJKH.040: DI ×100 soup must not authorize inflated agent BOX28."""
    auth, reason = authorize_conflict_agent_charge(
        "1571.63",
        candidates=[
            {"engine": "azure_document_intelligence_read", "value": "157163.00"},
            {"engine": "anthropic_claude_crop", "value": "1571.63"},
        ],
        service_lines=[{"charges": "157.00"}],
    )
    assert auth is None
    assert reason == "CONFLICT_AGENT_SOLE_AUTHORITY"


def test_geometry_underread_does_not_override_agent_box28():
    """DJKH.040: geo whole-dollar invent must not reject agent BOX28 pick."""
    # Payload shaped so geometry underread would recover a disagreeing amount.
    payload = {
        "candidates": [
            {
                "engine": "rapidocr",
                "value": "5.16",
                "raw_value": "516",
                "preprocessing_variant": "GEOMETRY_CENTS_UNDERREAD",
            },
            {"engine": "anthropic_claude_crop", "value": "1571.63"},
            {"engine": "azure_document_intelligence_read", "value": "157163.00"},
        ],
        "attempts": [
            {
                "reason": "GEOMETRY_CENTS_UNDERREAD",
                "raw_value": "516",
                "value": "5.16",
            }
        ],
    }
    result = ClaimEvidenceBuilder.load().build(
        claim_id="DJKH.040",
        document_family="CMS1500",
        claim_values={
            "total_charge": "1571.63",
            "_financial_conflict_agent": {
                "side": "BOX28",
                "value": "1571.63",
                "reason": "CONFLICT_AGENT_FINANCIAL_RESOLVED",
            },
            "_box28_field_payload": payload,
        },
        service_lines=[{"charges": "157.00"}],
    )
    geo_overrides = [
        i
        for i in result.evidence_items
        if i.evidence_type == "CLAIM_TOTAL_CONFIRMED"
        and (i.metadata or {}).get("reason") == "GEOMETRY_UNDERREAD_WHOLE_DOLLAR_BOX28"
    ]
    assert geo_overrides == []


def test_vision_local_inflated_scale_rival_stays_hitl():
    """DJKH.040: vision+local 1571.63 beside DI 157163 must not AUTO."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _cand("anthropic_claude_crop", "1571.63"),
            _cand("paddleocr", "1571.63", raw_value="157163"),
            _cand("azure_document_intelligence_read", "157163.00"),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CHARGE_VISION_LOCAL_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"1571.63"},
    )
    assert result.decision != Decision.ACCEPT
    assert "CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL" in result.rationale_codes


def test_l5_unique_calendar_dob_mints_independent_e2():
    """EJG7.007: sole Claude calendar DOB still mints independent E2."""
    bundle = build_evidence_bundle(
        field_name="patient_dob",
        candidates=[_cand("anthropic_claude_crop", "01/06/1975", 0.72)],
        registration_confidence=0.9,
        wrong_crop_suspected=False,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        hard_validation_passed=True,
    )
    e2 = [
        item
        for item in bundle.items
        if item.evidence_class.value == "E2" and item.independent
    ]
    assert e2
    assert (e2[0].metadata or {}).get("agreement_type") == (
        "DATE_UNIQUE_CALENDAR_CORROBORATED"
    )


def test_ejge_vision_underread_authorizes_and_mints_e4():
    """EJGE.016/032: Claude 300/250 vs paddle underread scrap → E4 + authorize."""
    auth, reason = authorize_conflict_agent_charge(
        "300.00",
        candidates=[
            {"engine": "anthropic_claude_crop", "value": "300.00"},
            {"engine": "paddleocr", "value": "29.00"},
            {"engine": "rapidocr", "value": "3:TOTAL CHARGE"},
        ],
    )
    assert auth == "300.00"
    assert reason == "VISION_CORROBORATES_CONFLICT_PICK"

    # Inflated local rival must stay HITL (not underread).
    auth_bad, reason_bad = authorize_conflict_agent_charge(
        "300.00",
        candidates=[
            {"engine": "anthropic_claude_crop", "value": "300.00"},
            {"engine": "paddleocr", "value": "3000.00"},
        ],
    )
    assert auth_bad is None
    assert reason_bad == "CONFLICT_AGENT_SOLE_AUTHORITY"

    # Exact vision+local agree without underread scrap — not this path
    # (DJKN.022 Claude+paddle 25 vs line Σ 450 must not AUTO via underread).
    auth_agree, reason_agree = authorize_conflict_agent_charge(
        "25.00",
        candidates=[
            {"engine": "anthropic_claude_crop", "value": "25.00"},
            {"engine": "paddleocr", "value": "25.00"},
        ],
        service_lines=[{"charges": "450.00"}],
    )
    assert auth_agree is None
    assert reason_agree == "CONFLICT_AGENT_SOLE_AUTHORITY"

    # DJKN.023: Claude hallucinated 45000 vs rapid 11 — extreme ratio, stay HITL.
    auth_huge, reason_huge = authorize_conflict_agent_charge(
        "45000.00",
        candidates=[
            {"engine": "anthropic_claude_crop", "value": "45000.00"},
            {"engine": "rapidocr", "value": "11.00"},
        ],
    )
    assert auth_huge is None
    assert reason_huge == "CONFLICT_AGENT_SOLE_AUTHORITY"

    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("anthropic_claude_crop", "300.00"),
            _cand("paddleocr", "29.00"),
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

    # Extreme ratio must not mint underread E4 either.
    bundle_bad = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("anthropic_claude_crop", "45000.00"),
            _cand("rapidocr", "11.00"),
        ],
        registration_confidence=0.9,
        wrong_crop_suspected=False,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        hard_validation_passed=True,
    )
    facts_bad = {
        (item.metadata or {}).get("fact")
        for item in bundle_bad.items
        if item.metadata
    }
    assert "CHARGE_VISION_LOCAL_CONFIRMED" not in facts_bad

    result = ClaimEvidenceBuilder.load().build(
        claim_id="EJGE.016",
        document_family="CMS1500",
        claim_values={
            "total_charge": "300.00",
            "_financial_conflict_agent": {
                "side": "BOX28",
                "value": "300.00",
                "reason": "CONFLICT_AGENT_FINANCIAL_RESOLVED",
            },
            "_box28_field_payload": {
                "candidates": [
                    {"engine": "anthropic_claude_crop", "value": "300.00"},
                    {"engine": "paddleocr", "value": "29.00"},
                ]
            },
        },
        service_lines=[],
    )
    confirmed = [
        i
        for i in result.evidence_items
        if i.evidence_type == "CLAIM_TOTAL_CONFIRMED"
    ]
    assert confirmed
    assert all(str(i.value) == "300.00" for i in confirmed)
    reasons = {(i.metadata or {}).get("reason") for i in confirmed}
    assert "VISION_CORROBORATES_CONFLICT_PICK" in reasons


def test_ejge005_di_local_clears_geometry_glue_and_rapid_93():
    """EJGE.005: DI+paddle 19.00 owns; geometry 9300.19 / rapid 93 are soup."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _cand("azure_document_intelligence_read", "19.00"),
            _cand("paddleocr", "19.00"),
            _cand("rapidocr", "9300.19"),
            _cand("rapidocr", "93.00"),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CHARGE_DI_LOCAL_CONFIRMED",
            "MULTI_ENGINE_AGREEMENT",
            "BOX28_BLANKNESS_EVALUATED",
            "BOX28_LINE_SUM_EVALUATED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"19", "19.00"},
    )
    assert result.selected_value == "19.00"
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_ejge_inflated_digit_drop_twin_still_hitl_under_di_local():
    """Precision guard: DI-local 200 vs digit-drop 2001 stays CONFLICT (DJKN.005)."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _cand("azure_document_intelligence_read", "200.00"),
            _cand("paddleocr", "200.00"),
            _cand("rapidocr", "2001.00"),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CHARGE_DI_LOCAL_CONFIRMED",
            "MULTI_ENGINE_AGREEMENT",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"200", "200.00"},
    )
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes or (
        result.decision != Decision.ACCEPT
    )
