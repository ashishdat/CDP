"""gpt-4o ID residual vs weak-local / digit-conflict relief (v12.3o)."""

from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.candidate_reconciliation.reconciler import (
    _is_azure_gpt4o_crop_engine,
    _member_id_is_weak_for_gpt4o_gate,
    _member_ids_share_digit_prefix,
)
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence.builder import engine_family
from packages.extraction_recovery.gpt4o_crop_residual import (
    id_local_digit_conflict,
    id_needs_gpt4o,
)
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group


def _candidate(value: str, engine: str, confidence: float = 0.999) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="1",
        preprocessing_variant="original",
        raw_confidence=confidence,
        calibrated_confidence=None,
        bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100),
        latency_ms=1,
    )


def test_gpt4o_independence_group_is_cloud_ai_not_azure_read():
    assert independence_group("azure_gpt4o_crop") == "CLOUD_AI_FAMILY"
    assert independence_group("azure_document_intelligence_read") == "AZURE_READ_FAMILY"
    assert engine_family("azure_gpt4o_crop") == "CLOUD_AI_FAMILY"
    assert _is_azure_gpt4o_crop_engine("azure_gpt4o_crop")
    assert not _is_azure_gpt4o_crop_engine("azure_document_intelligence_read")


def test_weak_local_gate_helpers():
    assert _member_id_is_weak_for_gpt4o_gate("338977")
    assert _member_id_is_weak_for_gpt4o_gate("20755")
    assert not _member_id_is_weak_for_gpt4o_gate("33847173")
    assert not _member_id_is_weak_for_gpt4o_gate("949774145")
    assert _member_ids_share_digit_prefix("33847173", "338977")
    assert not _member_ids_share_digit_prefix("909293380", "555555555")


def test_id_local_digit_conflict_gate():
    assert id_local_digit_conflict(
        [
            {"value": "909295500", "engine": "paddleocr"},
            {"value": "909293380", "engine": "rapidocr"},
        ]
    )
    # Confusable J↔U is not a digit conflict for the residual gate.
    assert not id_local_digit_conflict(
        [
            {"value": "JSW000179858", "engine": "paddleocr"},
            {"value": "USW000179858", "engine": "rapidocr"},
        ]
    )
    assert id_needs_gpt4o(
        "909293380",
        accepted=True,
        candidates=[
            {"value": "909295500", "engine": "paddleocr"},
            {"value": "909293380", "engine": "rapidocr"},
        ],
    )
    assert not id_needs_gpt4o(
        "949774145",
        accepted=True,
        candidates=[{"value": "949774145", "engine": "rapidocr"}],
    )


def test_gpt4o_vs_weak_local_id_conflict_relieved():
    """HJE5.016-class: gpt-4o 33847173 vs rapid 338977 → ACCEPT."""
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("33847173", "azure_gpt4o_crop", 0.95),
            _candidate("338977", "rapidocr", 0.90),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "33847173"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes
    assert "GPT4O_ID_WEAK_LOCAL_RELIEVED" in result.rationale_codes


def test_weak_local_ranked_first_still_prefers_gpt4o():
    """When ranking crowns short rapid, reconcile still prefers gpt-4o residual."""
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("338977", "rapidocr", 0.97),
            _candidate("33847173", "azure_gpt4o_crop", 0.95),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "33847173"
    assert "GPT4O_ID_WEAK_LOCAL_RELIEVED" in result.rationale_codes
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_genuine_same_length_digit_conflict_stays_hitl_without_gpt4o():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("909295500", "paddleocr", 0.975),
            _candidate("909293380", "rapidocr", 0.990),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes


def test_gpt4o_tiebreak_same_length_digit_conflict():
    """DJJM.037-class: gpt-4o agrees with rapid → drop paddle twin."""
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("909295500", "paddleocr", 0.975),
            _candidate("909293380", "rapidocr", 0.990),
            _candidate("909293380", "azure_gpt4o_crop", 0.95),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "909293380"
    assert "GPT4O_ID_DIGIT_CONFLICT_TIEBREAK" in result.rationale_codes
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_gpt4o_alone_third_value_keeps_hitl():
    """gpt-4o invents a third ID matching neither local → stay HITL."""
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("909295500", "paddleocr", 0.975),
            _candidate("909293380", "rapidocr", 0.990),
            _candidate("909291111", "azure_gpt4o_crop", 0.99),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes


def test_gpt4o_prior_divergence_keeps_hitl():
    """No shared digit prefix → do not relieve (safety gate)."""
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("849774145", "azure_gpt4o_crop", 0.95),
            _candidate("338977", "rapidocr", 0.90),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes
    assert "GPT4O_ID_WEAK_LOCAL_RELIEVED" not in result.rationale_codes
