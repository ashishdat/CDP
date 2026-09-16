"""Independent use-case tests for v11.6 residual field HITL reliefs.

Batch of 15: 7 targeted generalizable fixes + 8 honest HITL controls.
Each rule uses synthetic examples (not claim IDs) so reliefs stay reusable.
"""

from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.candidate_reconciliation.reconciler import (
    _member_id_is_length_fragment,
    _member_ids_differ_by_prefix_bleed,
    prefer_member_id_longer_authority,
    values_conflict_equivalent,
)
from packages.criticality import CriticalityLevel
from packages.deterministic_evidence.service import DeterministicEvidenceService
from packages.domain.common import BoundingBox
from packages.field_normalization import normalize_member_id
from packages.ocr.contracts import OCRCandidate


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


# --- 1) Member ID: spaced OCR still FORMAT_VALID ----------------------------


def test_independent_spaced_member_id_format_valid():
    svc = DeterministicEvidenceService()
    assert svc.evaluate("insured_id_number", "4E80 VH6 HJ14").passed
    assert "FORMAT_VALID" in svc.evaluate("insured_id_number", "4E80 VH6 HJ14").evidence
    assert svc.evaluate("insured_id_number", "G62 387 94n").passed
    compact, ok = normalize_member_id("4E80 VH6 HJ14")
    assert ok and compact == "4E80VH6HJ14"


def test_independent_spaced_member_id_reconcile_accepts():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("4E80 VH6 HJ14", "paddleocr", 0.98),
            _candidate("4E80 VH6 HJ14", "rapidocr", 0.99),
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
    assert result.selected_value == "4E80VH6HJ14"


# --- 2) Member ID: punctuated OCR compact form -----------------------------


def test_independent_punctuated_member_id_format_valid():
    svc = DeterministicEvidenceService()
    assert svc.evaluate("insured_id_number", "907.549 6.30 -00").passed
    assert svc.evaluate("insured_id_number", "05G 773.08084- 01").passed


# --- 3) Member ID: short fragment vs full number ---------------------------


def test_independent_member_id_length_fragment():
    assert _member_id_is_length_fragment("981366", "98126619000")
    assert values_conflict_equivalent("insured_id_number", "981366", "98126619000")
    assert prefer_member_id_longer_authority("981366", ["981 266 190 - 00"]) == (
        "981 266 190 - 00"
    )
    # Same-length digit conflicts are NOT fragments
    assert not _member_id_is_length_fragment("909293380", "909295500")


def test_independent_member_id_fragment_reconcile_accepts():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("981366", "paddleocr", 0.72),
            _candidate("981 266 190 - 00", "rapidocr", 0.75),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "98126619000"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


# --- 4) Member ID: tesseract-only disagreement ignored ---------------------


def test_independent_member_id_tesseract_only_conflict_relieved():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("907.549 6.30 -00", "rapidocr", 0.96),
            _candidate("GO7SY9L340CO", "tesseract", 0.27),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "90754963000"


# --- 5) Member ID: J↔U confusable ------------------------------------------


def test_independent_member_id_ju_confusable():
    assert values_conflict_equivalent(
        "insured_id_number", "JSW000179858", "USW000179858"
    )
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("JSW000179858", "paddleocr", 0.996),
            _candidate("USW000179858", "rapidocr", 0.998),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


# --- 6) Member ID: leading prefix bleed ------------------------------------


def test_independent_member_id_prefix_bleed():
    assert _member_ids_differ_by_prefix_bleed("OSC75615107", "C75615107")
    assert values_conflict_equivalent("insured_id_number", "OSC75615107", "C75615107")
    assert prefer_member_id_longer_authority("C75615107", ["OSC75615107"]) == (
        "OSC75615107"
    )
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("C75615107", "paddleocr", 0.91),
            _candidate("OSC75615107", "rapidocr", 0.95),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "OSC75615107"


# --- 7) Name: L↔H confusable (+ optional MI) -------------------------------


def test_independent_name_lh_confusable():
    assert values_conflict_equivalent(
        "patient_name", "MCLARTY CARON A", "MCHARTY CARON A"
    )
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("MCLARTY CARON A", "paddleocr", 0.93),
            _candidate("MCHARTY.- CARON A", "rapidocr", 0.81),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


# --- 8–15) Honest HITL controls --------------------------------------------


def test_independent_genuine_digit_id_conflict_stays_hitl():
    assert not values_conflict_equivalent(
        "insured_id_number", "909293380", "909295500"
    )
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


def test_independent_genuine_near_digit_id_conflict_stays_hitl():
    assert not values_conflict_equivalent(
        "insured_id_number", "993161471", "993161411"
    )
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("993161411", "paddleocr", 0.980),
            _candidate("993161471", "rapidocr", 0.995),
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


def test_independent_genuine_dob_conflict_stays_hitl():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("05/02/2010", "paddleocr", 0.97),
            _candidate("02/20/2005", "rapidocr", 0.95),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID", "DATE_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW


def test_independent_name_unrelated_stays_hitl_viti():
    assert not values_conflict_equivalent("patient_name", "VITI DAVID", "ILIA DAVID")
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("VITI DAVID", "paddleocr", 0.96),
            _candidate("ILIA DAVID", "rapidocr", 0.94),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW


def test_independent_name_unrelated_stays_hitl_perri():
    assert not values_conflict_equivalent("patient_name", "PERRI SOPHIA", "PEMI SOPHIA")


def test_independent_empty_charge_not_invented():
    from packages.claim_evidence.line_sum_authority import (
        line_sum_total,
        should_defer_box28_to_line_sum,
    )

    assert line_sum_total([]) is None
    assert line_sum_total(None) is None
    assert not should_defer_box28_to_line_sum(None, [])
    result = EvidenceReconciler().reconcile(
        "total_charge",
        [],
        CriticalityLevel.C2,
        deterministic_evidence=set(),
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision in {Decision.ESCALATE, Decision.REVIEW, Decision.ABSTAIN}
    assert result.selected_value in (None, "")


def test_independent_handwriting_dob_garbage_stays_hitl():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("MM 一 DD Y 1 1 1", "paddleocr", 0.55),
            _candidate("MM YY 1", "rapidocr", 0.60),
        ],
        CriticalityLevel.C2,
        deterministic_evidence=set(),
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision in {Decision.ESCALATE, Decision.REVIEW}


def test_independent_future_dob_stays_hitl():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [_candidate("01/01/2034", "rapidocr", 0.90)],
        CriticalityLevel.C2,
        deterministic_evidence=set(),
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "FUTURE_DOB_REJECTED" in result.rationale_codes
