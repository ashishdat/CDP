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


def test_acosta_ou_and_hector_ti_confusable():
    """EJG7.007: Claude ACOSTA,HECTOR vs rapid ACUSTA,HECIOR (O↔U + T↔I)."""
    assert values_conflict_equivalent(
        "patient_name", "ACOSTA, HECTOR", "ACUSTA, HECIOR"
    )
    assert values_conflict_equivalent("patient_name", "ACOSTA", "ACUSTA")
    assert values_conflict_equivalent("patient_name", "HECTOR", "HECIOR")
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("ACOSTA, HECTOR", "azure_gpt4o_crop", 0.94),
            _candidate("ACUSTA, HECIOR", "rapidocr", 0.91),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "BOX2_BOX4_NAME_CONFIRMED",
            "MEMBER_RELATIONSHIP_CONFIRMED",
            "MULTI_ATTRIBUTE_IDENTITY_CONFIRMED",
        },
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


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


def test_member_id_o0_confusable_substitution():
    assert values_conflict_equivalent(
        "insured_id_number", "A00046372APU", "A00046372AP0"
    )
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("A00046372APU", "rapidocr", 0.9988),
            _candidate("A00046372AP0", "paddleocr", 0.9408),
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


def test_dob_january_dash_artifact_prefers_true_month():
    from packages.candidate_reconciliation.reconciler import (
        prefer_dob_without_january_dash_artifact,
    )

    assert (
        prefer_dob_without_january_dash_artifact("07/24/1955", ["01/24/1955"])
        == "07/24/1955"
    )
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("07/24/1955", "paddleocr", 0.9919),
            _candidate("01/24/1955", "rapidocr", 0.9012),
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
    assert result.selected_value == "07/24/1955"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_dob_genuine_month_day_conflict_stays_hitl():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("12/29/1999", "rapidocr", 0.8954),
            _candidate("01/22/1999", "paddleocr", 0.8739),
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


def test_multi_engine_padded_member_id_accepts_over_letter_soup():
    """Group A__M048EJG7.036: paddle+rapid (+vision) ``0000007267`` beats
    tesseract letter soup. Lone padded shells still fail closed elsewhere.
    """
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("0000007267", "anthropic_claude_crop", 0.99),
            _candidate("eee ae | ONNNAAIVKRT", "tesseract", 0.55),
            _candidate("0000007267", "paddleocr", 0.79),
            _candidate("0000007267", "rapidocr", 0.77),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "0000007267"
    assert "UNSHAPED_MEMBER_ID" not in result.rationale_codes


def test_lone_padded_member_id_shell_stays_review():
    """Single-engine zero-padded short shell must not AUTO as a subscriber id."""
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [_candidate("0000007267", "paddleocr", 0.90)],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.REVIEW
    assert "UNSHAPED_MEMBER_ID" in result.rationale_codes


def test_same_self_reference_beats_single_token_soup():
    """Box 4 ``SAME`` is the insured name. OCR soup must not replace it."""
    result = EvidenceReconciler().reconcile(
        "insured_name",
        [
            _candidate("SAME", "anthropic_claude_crop", 0.96),
            _candidate("SAME", "anthropic_claude_crop", 0.95),
            _candidate("pmmLainnm 2", "rapidocr", 0.77),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "SAME"


def test_box_rule_digit_does_not_beat_clean_name_tokens():
    """``EMILY, A 2 CARTIER`` is form-rule junk beside ``CARTIER, EMILY``."""
    result = EvidenceReconciler().reconcile(
        "insured_name",
        [
            _candidate("CARTIER, EMILY", "anthropic_claude_crop", 0.97),
            _candidate("CARTIER, EMILY", "anthropic_claude_crop", 0.96),
            _candidate("EMILY, A 2 CARTIER", "paddleocr", 0.985),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "CARTIER, EMILY"


def test_trailing_middle_initial_still_preferred_without_a_digit():
    """Do not drop a trailing initial when no box-rule digit is present."""
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("GAVIN. ROBERT, M", "anthropic_claude_crop", 0.96),
            _candidate("GAVIN. ROBERT, M", "paddleocr", 0.968),
            _candidate("GAVIN, ROBERT", "anthropic_claude_crop", 0.97),
            _candidate("GAVIN, ROBERT", "rapidocr", 0.998),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        independent_agreement_values=set(),
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.selected_value == "GAVIN. ROBERT, M"


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
    assert (
        "FORMAT_VALID_ID_THRESHOLD_RELIEF" in result.rationale_codes
        or "UNIQUE_SHAPED_ID_CORROBORATED" in result.rationale_codes
    )


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
