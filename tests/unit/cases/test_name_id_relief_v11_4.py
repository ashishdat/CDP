"""Unit tests for v11.4 name confusable/title + ID format-valid floor relief."""

from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.candidate_reconciliation.reconciler import (
    _dob_is_future,
    _names_differ_by_glued_vs_spaced,
    _names_differ_by_leading_junk_initial,
    _names_differ_by_shared_given_name,
    _names_differ_by_trailing_digit_junk,
    values_conflict_equivalent,
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


def test_jeffrey_ef_confusable():
    assert values_conflict_equivalent(
        "patient_name", "ALSBURY JEFFREY", "ALSBURY JEFEREY"
    )


def test_joyce_vy_confusable():
    assert values_conflict_equivalent(
        "patient_name", "WILLIAMS JOVCE", "WILLIAMS JOYCE"
    )


def test_praznikholst_ty_confusable():
    assert values_conflict_equivalent(
        "patient_name", "PRAZNIKHOLST BRITIENY", "PRAZNIKHOLSY BRITIENY"
    )


def test_laflora_ef_confusable():
    assert values_conflict_equivalent(
        "patient_name", "LAELORA CHRISTINA R", "LAFLORA CHRISTINA R"
    )


def test_grant_gc_confusable():
    assert values_conflict_equivalent("patient_name", "GRANT JASON", "CRANT JASON")


def test_mrs_title_strip_shared_given():
    assert _names_differ_by_shared_given_name("BEAUDOINMRS CHERYL", "MRS CHERYLA")
    assert values_conflict_equivalent(
        "patient_name", "BEAUDOINMRS, CHERYL", "MRS CHERYLA"
    )


def test_same_z_token_order():
    assert values_conflict_equivalent("insured_name", "Z SAME", "SAME Z")


def test_same_trailing_digit_junk():
    assert _names_differ_by_trailing_digit_junk("SAME", "SAME 2")
    assert values_conflict_equivalent("insured_name", "SAME", "SAME 2")


def test_leading_junk_initial_with_confusable():
    assert _names_differ_by_leading_junk_initial(
        "ALSBURY JEFEREY", "Z ALSBURY JEFFREY"
    )
    assert values_conflict_equivalent(
        "insured_name", "ALSBURY JEFEREY", "Z ALSBURY JEFFREY"
    )


def test_olenik_optional_mi_with_confusable():
    assert values_conflict_equivalent(
        "patient_name", "OLENIK MICHAEL J", "OLFNIK MICHAEL"
    )


def test_murphy_glued_vs_spaced():
    assert _names_differ_by_glued_vs_spaced("MURPHYPATRICK", "MURPHYP PATRICK")
    assert values_conflict_equivalent(
        "insured_name", "MURPHYPATRICK", "MURPHYP PATRICK"
    )


def test_viti_ilia_not_equivalent():
    # 4-letter surname disagreement — keep HITL (false-accept risk).
    assert not values_conflict_equivalent("patient_name", "VITI DAVID", "ILIA DAVID")


def test_member_id_confusable_l_insertion():
    assert values_conflict_equivalent(
        "insured_id_number", "A00046372APU", "A00046372APLU"
    )
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("A00046372APU", "rapidocr", 0.999),
            _candidate("A00046372APLU", "paddleocr", 0.971),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "A00046372APU"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_member_id_digit_conflict_stays_hitl():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("909293380", "rapidocr", 0.96),
            _candidate("909295500", "paddleocr", 0.94),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes

    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("119596855", "rapidocr", 0.7975),
            _candidate("119596855", "paddleocr", 0.7122),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "MULTI_ENGINE_ID_CORROBORATED_THRESHOLD_RELIEF" in result.rationale_codes
    assert "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" not in result.rationale_codes


def test_id_format_valid_floor_single_engine():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [_candidate("4244409", "paddleocr", 0.9276)],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "FORMAT_VALID_ID_THRESHOLD_RELIEF" in result.rationale_codes


def test_id_identity_corroborated_near_miss():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("986993070", "paddleocr", 0.8396),
            _candidate("986993070", "rapidocr", 0.8015),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" not in result.rationale_codes


def test_future_dob_rejected():
    assert _dob_is_future("2034-01-01")
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [_candidate("01/01/2034", "rapidocr", 0.95)],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "FUTURE_DOB_REJECTED" in result.rationale_codes


def test_future_digit_glue_does_not_block_unique_dob():
    """Paddle year-5199 glue must not starve tesseract's only real DOB."""
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("05/15/1997", "tesseract", 0.37),
            _candidate("05 115199", "paddleocr", 0.97),
            _candidate("MM 5 1 1 Q D", "rapidocr", 0.85),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert _dob_is_future(result.selected_value or "") is False
    assert "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" not in result.rationale_codes


def test_name_mi_relief_does_not_accept_dob_year_conflict():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("01/09/1960", "rapidocr", 0.92),
            _candidate("09/09/2015", "paddleocr", 0.89),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes
    assert "NAME_MIDDLE_INITIAL_RELIEVED" not in result.rationale_codes


def test_name_conflict_jeffrey_accepts():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("ALSBURY JEFFREY", "rapidocr", 0.997),
            _candidate("ALSBURY JEFEREY", "paddleocr", 0.946),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes
