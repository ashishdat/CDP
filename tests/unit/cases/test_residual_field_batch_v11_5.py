"""Independent use-case tests for v11.5 residual field HITL reliefs.

Each rule is exercised with synthetic examples (not claim IDs) so the fix is
reusable beyond the Track-B 15-field batch.
"""

from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.candidate_reconciliation.reconciler import (
    prefer_dob_without_january_dash_artifact,
    prefer_dob_year_confusable_digit,
    values_conflict_equivalent,
)
from packages.claim_evidence.line_sum_authority import (
    line_sum_total,
    should_defer_box28_to_line_sum,
)
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
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


# --- 1) Charge: single-line wild contradiction → line sum -------------------


def test_independent_line_sum_defers_wild_box28():
    lines = [{"charges": "305.00"}]
    assert should_defer_box28_to_line_sum("22.00", lines)
    assert should_defer_box28_to_line_sum("9.99", lines)
    assert not should_defer_box28_to_line_sum("280.00", lines)  # within 50%
    assert line_sum_total(lines) == "305.00"


def test_independent_line_sum_multi_line_unchanged():
    lines = [{"charges": "200.00"}, {"charges": "100.00"}]
    assert should_defer_box28_to_line_sum("900.00", lines)
    assert not should_defer_box28_to_line_sum("300.00", lines)


# --- 2) DOB: January dash artifact -----------------------------------------


def test_independent_dob_january_artifact_examples():
    assert prefer_dob_without_january_dash_artifact("07/24/1955", ["01/24/1955"]) == "07/24/1955"
    assert prefer_dob_without_january_dash_artifact("03/15/1980", ["01/15/1980"]) == "03/15/1980"
    # Different day → not an artifact
    assert prefer_dob_without_january_dash_artifact("07/24/1955", ["01/25/1955"]) is None
    assert values_conflict_equivalent("patient_dob", "07/24/1955", "01/24/1955")


def test_independent_dob_january_reconcile_accepts():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("07/24/1955", "paddleocr", 0.99),
            _candidate("01/24/1955", "rapidocr", 0.90),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID", "DATE_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "07/24/1955"


# --- 3) DOB: year single-digit confusable (6↔9) ----------------------------


def test_independent_dob_year_confusable_examples():
    assert prefer_dob_year_confusable_digit("05/20/1995", ["05/20/1965"]) == "05/20/1995"
    assert prefer_dob_year_confusable_digit("11/03/1988", ["11/03/1989"]) == "11/03/1988"
    # Month conflict → no
    assert prefer_dob_year_confusable_digit("05/20/1995", ["06/20/1965"]) is None
    # Multi-digit year diff → no
    assert prefer_dob_year_confusable_digit("05/20/1995", ["05/20/1975"]) is None
    assert values_conflict_equivalent("patient_dob", "05/20/1995", "05/20/1965")


def test_independent_dob_year_confusable_reconcile_accepts():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("05/20/1995", "paddleocr", 0.99),
            _candidate("05/20/1965", "rapidocr", 0.88),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID", "DATE_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "05/20/1995"


def test_independent_dob_genuine_year_conflict_stays_hitl():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("03/01/2007", "paddleocr", 0.92),
            _candidate("03/07/1990", "rapidocr", 0.89),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID", "DATE_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW


# --- 4) Member ID: single confusable substitution --------------------------


def test_independent_member_id_confusable_subs():
    assert values_conflict_equivalent("insured_id_number", "A00046372APU", "A00046372AP0")
    assert values_conflict_equivalent("insured_id_number", "OSC05799655", "QSC05799655")
    assert values_conflict_equivalent("insured_id_number", "ABC00012O", "ABC000120")
    # Digit identity conflicts stay conflicts
    assert not values_conflict_equivalent("insured_id_number", "909293380", "909295500")
    assert not values_conflict_equivalent("insured_id_number", "993161471", "993161411")


def test_independent_member_id_u0_reconcile():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("A00046372APU", "rapidocr", 0.998),
            _candidate("A00046372AP0", "paddleocr", 0.941),
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
    assert result.selected_value == "A00046372APU"


def test_independent_member_id_oq_reconcile():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("OSC05799655", "rapidocr", 0.98),
            _candidate("QSC05799655", "paddleocr", 0.97),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT


# --- 5) Member ID: unique shaped vs OCR junk -------------------------------


def test_independent_unique_shaped_id_vs_junk():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("A22629904", "rapidocr", 0.75),
            _candidate("R &Q) 4g0 l", "paddleocr", 0.55),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "A22629904"
    assert "UNIQUE_SHAPED_ID_CORROBORATED" in result.rationale_codes


# --- 6) Name: confusable edit (delete vowel + one sub) ---------------------


def test_independent_name_confusable_edit():
    assert values_conflict_equivalent("patient_name", "MCGRATH PATRICIA", "MCGRATH FATRCIA")
    assert values_conflict_equivalent("patient_name", "PATRICIA SMITH", "FATRCIA SMITH")
    # Unrelated names stay conflicts
    assert not values_conflict_equivalent("patient_name", "VITI DAVID", "ILIA DAVID")
    assert not values_conflict_equivalent("patient_name", "PERRI SOPHIA", "PEMI SOPHIA")


def test_independent_name_patricia_reconcile():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("MCGRATH PATRICIA", "rapidocr", 0.999),
            _candidate("MCGRATH FATRCIA", "paddleocr", 0.978),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes
