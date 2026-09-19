"""gpt-4o crop residual as person-name ink arbitrator (v12.3 name ink)."""

from packages.candidate_reconciliation import Decision, EvidenceReconciler
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
        bounding_box=BoundingBox(
            x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100
        ),
        latency_ms=1,
    )


def test_gpt4o_prefers_over_conflicting_local_name_groups():
    """Claim-002-class: paddle MI glue vs unrelated rapid vs gpt-4o → ACCEPT gpt."""
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("THOMAS.DARLENE.M", "paddleocr", 0.99),
            _candidate("SMITH JOHN", "rapidocr", 0.97),
            _candidate("THOMAS DARLENE", "azure_gpt4o_crop", 0.85),
        ],
        CriticalityLevel.C1,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "THOMAS DARLENE"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes
    assert "GPT4O_NAME_INK_CONFLICT_RELIEVED" in result.rationale_codes


def test_gpt4o_soft_joins_local_and_relieves_mi_conflict():
    """gpt-4o + rapid share THOMAS DARLENE; paddle MI glue loses."""
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("THOMAS.DARLENE.M", "paddleocr", 0.99),
            _candidate("THOMAS, DARLENE", "rapidocr", 0.97),
            _candidate("THOMAS DARLENE", "azure_gpt4o_crop", 0.85),
        ],
        CriticalityLevel.C1,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "THOMAS DARLENE"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes
    assert "GPT4O_NAME_INK_CONFLICT_RELIEVED" in result.rationale_codes


def test_genuine_name_conflict_without_gpt4o_stays_hitl():
    """Two strong disagreeing locals without gpt-4o remain CONFLICT_MARGIN."""
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("CAMARATO JOSEPH", "paddleocr", 0.92),
            _candidate("WILLIAMS ANN", "rapidocr", 0.90),
        ],
        CriticalityLevel.C1,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes
    assert "GPT4O_NAME_INK_CONFLICT_RELIEVED" not in result.rationale_codes
