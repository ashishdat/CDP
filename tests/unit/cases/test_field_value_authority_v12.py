"""Independent use-case tests for v12 Field Value Authority redesign.

Batch of 15 residual patterns: 7 authority fixes + 8 honest HITL controls.
"""

from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.field_value_authority import (
    are_equivalent,
    field_family,
    is_authoritative_shape,
    prefer_authority,
)
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


# --- Authority API -----------------------------------------------------------


def test_field_family_routing():
    assert field_family("insured_id_number") == "member_id"
    assert field_family("patient_name") == "name"
    assert field_family("patient_dob") == "dob"
    assert field_family("total_charge") == "charge"


def test_authority_short_fragment_name():
    decision = prefer_authority("insured_name", "Ace", ["Maraafet Kalomatis 172"])
    assert decision.equivalent
    assert "Maraafet" in (decision.selected_value or "")
    assert decision.reason_code == "NAME_FRAGMENT_AUTHORITY"
    assert are_equivalent("insured_name", "Ace", "Maraafet Kalomatis 172")


def test_authority_vowel_skeleton_name():
    assert are_equivalent("patient_name", "LAURA", "LUR")
    decision = prefer_authority("patient_name", "LUR", ["LAURA"])
    assert decision.selected_value == "LAURA"


def test_authority_truncated_secondary_name():
    assert are_equivalent("patient_name", "BET IT", "Bet.t.t DOMTNIC")
    decision = prefer_authority("patient_name", "BET IT", ["Bet.t.t DOMTNIC"])
    assert "DOMTNIC" in (decision.selected_value or "").upper()


def test_authority_shared_core_token_name():
    assert are_equivalent("patient_name", "DUDAN", "DOCTNIKCS DOUDAN")
    decision = prefer_authority("patient_name", "DUDAN", ["DOCTNIKCS DOUDAN"])
    assert "DOUDAN" in (decision.selected_value or "").upper()


def test_authority_compact_member_id():
    decision = prefer_authority("insured_id_number", "4E80 VH6 HJ14", [])
    assert decision.selected_value == "4E80VH6HJ14"
    assert is_authoritative_shape("insured_id_number", "4E80VH6HJ14")


def test_authority_member_id_fragment():
    assert are_equivalent("insured_id_number", "981366", "98126619000")
    decision = prefer_authority(
        "insured_id_number", "981366", ["981 266 190 - 00"]
    )
    assert decision.selected_value == "98126619000"


# --- Reconciler integration --------------------------------------------------


def test_reconcile_short_fragment_insured_name_accepts():
    result = EvidenceReconciler().reconcile(
        "insured_name",
        [
            _candidate("Ace", "paddleocr", 0.81),
            _candidate("Maraafet Kalomatis 172", "rapidocr", 0.78),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "Ace" not in (result.selected_value or "")
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_reconcile_truncated_given_accepts():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("BET, IT", "rapidocr", 0.86),
            _candidate("Bet.t.t DOMTNIC", "paddleocr", 0.79),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "DOMTNIC" in (result.selected_value or "").upper()


def test_reconcile_vowel_skeleton_laura_accepts():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("LUR", "paddleocr", 0.82),
            _candidate("LAURA", "rapidocr", 0.91),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "LAURA"


# --- Honest HITL controls ----------------------------------------------------


def test_honest_unrelated_names_stay_hitl():
    assert not are_equivalent("patient_name", "VITI DAVID", "ILIA DAVID")
    assert not are_equivalent("patient_name", "PERRI SOPHIA", "PEMI SOPHIA")
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


def test_honest_digit_id_conflict_stays_hitl():
    assert not are_equivalent("insured_id_number", "909293380", "909295500")
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


def test_honest_dob_conflict_stays_hitl():
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


def test_honest_future_dob_stays_hitl():
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


def test_honest_empty_charge_not_invented():
    result = EvidenceReconciler().reconcile(
        "total_charge",
        [],
        CriticalityLevel.C2,
        deterministic_evidence=set(),
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision.value in {"ESCALATE", "REVIEW", "ABSTAIN"}
    assert result.selected_value in (None, "")


def test_authority_v12_2_insured_patient_ocr_twins():
    """Independent-300 v12.2: insured_name CONFLICT was OCR twin of patient_name."""
    assert are_equivalent("insured_name", "STERN SCART.ET", "STERN SOARTET")
    assert are_equivalent("insured_name", "KLUMP. COLLEEN", "KTIIMP COTTEEN")
    assert are_equivalent("insured_name", "KLUMP COLLEEN", "KIIMP COT.LEEN")
    # Short fragment insured vs strong patient remains equivalent (fragment path).
    assert are_equivalent("insured_name", "FUENTESPEDRO", "2 DD")
    # Unrelated names stay conflicts.
    assert not are_equivalent("insured_name", "DOCTNIKCS DOUDAN", "POSTIMNYCZ BOHDAN")
