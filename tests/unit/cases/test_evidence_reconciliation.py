from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.confidence import CalibrationRegistry, IsotonicCalibration
from packages.criticality import CriticalityLevel, CriticalityPolicy
from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate


def _candidate(
    value: str,
    engine: str,
    confidence: float = 0.999,
    *,
    preprocessing_variant: str = "original",
    evidence_reference: str | None = None,
) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="1",
        preprocessing_variant=preprocessing_variant,
        raw_confidence=confidence,
        calibrated_confidence=None,
        bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100),
        latency_ms=1,
        evidence_reference=evidence_reference,
    )


def test_c3_rejects_single_engine_regardless_of_confidence():
    result = EvidenceReconciler().reconcile(
        "npi", [_candidate("1234567893", "rapidocr", 1.0)], CriticalityLevel.C3
    )
    assert result.decision == Decision.REVIEW
    assert "FIELD_EVIDENCE_POLICY_NOT_SATISFIED" in result.rationale_codes


def test_two_paddle_variants_are_not_independent_evidence():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "paddleocr"), _candidate("1234567893", "pp-ocr-v5")],
        CriticalityLevel.C3,
    )
    assert result.decision == Decision.REVIEW
    assert "MULTI_ENGINE_AGREEMENT" not in result.rationale_codes


def test_npi_accepts_independent_agreement_plus_checksum():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr"), _candidate("1234567893", "tesseract")],
        CriticalityLevel.C3,
        deterministic_evidence={"CHECKSUM_VALID"},
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "1234567893"
    assert "MULTI_ENGINE_AGREEMENT" in result.rationale_codes
    assert len([item for item in result.supporting_evidence if item.evidence_type == "OCR_CANDIDATE"]) == 2


def test_npi_checksum_alone_cannot_supply_complete_evidence():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr")],
        CriticalityLevel.C3,
        deterministic_evidence={"CHECKSUM_VALID"},
    )
    assert result.decision == Decision.REVIEW
    assert "CHECKSUM_VALID" in result.rationale_codes
    assert "FIELD_EVIDENCE_POLICY_NOT_SATISFIED" in result.rationale_codes


def test_unverified_reference_value_cannot_authorize_c3_acceptance():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr")],
        CriticalityLevel.C3,
        authoritative_value="1234567893",
    )
    assert result.decision == Decision.REVIEW
    assert "REFERENCE_MATCH" not in result.rationale_codes


def test_governed_reference_can_authorize_c3_acceptance():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr")],
        CriticalityLevel.C3,
        authoritative_value="1234567893",
        authoritative_reference_verified=True,
        authoritative_source="nppes-snapshot",
        authoritative_version="2026-08",
    )
    assert result.decision == Decision.REFERENCE_CONFIRMED
    assert "REFERENCE_MATCH" in result.rationale_codes
    reference = next(
        item for item in result.supporting_evidence
        if item.evidence_type == "AUTHORITATIVE_REFERENCE"
    )
    assert reference.source == "nppes-snapshot"
    assert reference.reference == "2026-08"


def test_governed_reference_contradiction_blocks_consensus_acceptance():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr"), _candidate("1234567893", "tesseract")],
        CriticalityLevel.C3,
        deterministic_evidence={"CHECKSUM_VALID"},
        authoritative_value="1999999999",
        authoritative_reference_verified=True,
        authoritative_source="nppes-snapshot",
        authoritative_version="2026-08",
    )
    assert result.decision == Decision.REVIEW
    assert "REFERENCE_CONTRADICTION" in result.rationale_codes
    assert any(
        item.reason_code == "REFERENCE_CONTRADICTION"
        for item in result.conflicting_evidence
    )


def test_calibrated_probability_not_raw_score_drives_threshold():
    registry = CalibrationRegistry(
        {("rapidocr", "member_id"): IsotonicCalibration((0.0, 1.0), (0.1, 0.7), "member-v2")}
    )
    result = EvidenceReconciler(registry).reconcile(
        "member_id", [_candidate("A123", "rapidocr", 0.99)], CriticalityLevel.C2
    )
    assert result.decision == Decision.ESCALATE
    assert result.calibration_model_version == "member-v2"


def test_criticality_policy_is_externalized():
    policy = CriticalityPolicy.load("config/field_criticality.yaml")
    assert policy.for_field("rendering_provider_npi") == CriticalityLevel.C3
    assert policy.for_field("unknown_optional") == CriticalityLevel.C1


def test_line_totals_e6_can_authorize_total_charge_without_second_engine():
    """Phase 2: corroborated line-sum E6 is financial authority for empty box-28."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [_candidate("400.00", "rapidocr")],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "LINE_TOTALS_RECONCILED",
            "LINE_TOTALS_CORROBORATED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "400.00"
    assert "LINE_TOTALS_RECONCILED" in result.rationale_codes
    assert "LINE_TOTALS_CORROBORATED" in result.rationale_codes


def test_line_sum_scale_twin_does_not_veto_the_smaller_total():
    """Box 28 25000 must not keep line Σ 250 in review once line totals own it."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _candidate(
                "250.00",
                "rapidocr",
                0.99,
                preprocessing_variant="DERIVED_FROM_OBSERVED_LINE_CHARGES",
                evidence_reference="LINE_TOTALS_RECONCILED",
            ),
            _candidate("25000.00", "paddleocr", 0.98),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "LINE_TOTALS_RECONCILED",
            "LINE_TOTALS_CORROBORATED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "250.00"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_inflated_box28_scale_twin_stays_in_review():
    """Do not auto-accept Box 28 25000 just because line Σ 250 is a scale twin."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _candidate("25000.00", "paddleocr", 0.99),
            _candidate(
                "250.00",
                "rapidocr",
                0.98,
                preprocessing_variant="DERIVED_FROM_OBSERVED_LINE_CHARGES",
                evidence_reference="LINE_TOTALS_RECONCILED",
            ),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "LINE_TOTALS_RECONCILED",
            "LINE_TOTALS_CORROBORATED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.selected_value == "25000.00"
    assert result.decision != Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes


def test_line_sum_fuller_digit_drop_does_not_veto_stp():
    """HJDF.022: line Σ 3402 must AUTO beside truncated Box OCR 340."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _candidate(
                "3402.00",
                "rapidocr",
                1.0,
                preprocessing_variant="DERIVED_FROM_OBSERVED_LINE_CHARGES",
                evidence_reference="LINE_TOTALS_RECONCILED",
            ),
            _candidate("340.00", "azure_document_intelligence_read", 0.97),
            _candidate("340.00", "anthropic_claude_crop", 0.96),
            _candidate("34000.00", "paddleocr", 0.90),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "LINE_TOTALS_RECONCILED",
            "LINE_TOTALS_CORROBORATED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        # Field decision passes E2-qualified values; truncated Box 340 is not E2.
        independent_agreement_values=set(),
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "3402.00"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_truncated_box_does_not_inherit_line_sum_soup_relief():
    """DI/Claude 340 must not AUTO when LINE_TOTALS evidence belongs to Σ 3402."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [
            _candidate("340.00", "azure_document_intelligence_read", 0.99),
            _candidate("340.00", "anthropic_claude_crop", 0.98),
            _candidate(
                "3402.00",
                "rapidocr",
                1.0,
                preprocessing_variant="DERIVED_FROM_OBSERVED_LINE_CHARGES",
                evidence_reference="LINE_TOTALS_RECONCILED",
            ),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "LINE_TOTALS_RECONCILED",
            "LINE_TOTALS_CORROBORATED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
        independent_agreement_values={"340"},
    )
    assert result.selected_value == "340.00"
    assert result.decision != Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" in result.rationale_codes


def test_line_totals_without_corroboration_does_not_financial_auto():
    """Bare LINE_TOTALS (no dual-engine / DI) must not E6-AUTO critical charge."""
    result = EvidenceReconciler(allow_authoritative_financial_e6=True).reconcile(
        "total_charge",
        [_candidate("424.00", "rapidocr")],
        CriticalityLevel.C3,
        deterministic_evidence={
            "FORMAT_VALID",
            "LINE_TOTALS_UNCORROBORATED",
            "LINE_TOTALS_GATE:MULTI_LINE_UNCORROBORATED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision != Decision.ACCEPT
    assert "LINE_TOTALS_CORROBORATED" not in result.rationale_codes


def test_identity_corroborated_threshold_relief_for_insured_id():
    """Member ID near C3 floor accepts when hard validation + relationship E6."""
    registry = CalibrationRegistry(
        {
            ("rapidocr", "insured_id_number"): IsotonicCalibration(
                (0.0, 1.0), (0.97, 0.97), "id-near-miss-v1"
            )
        }
    )
    reconciler = EvidenceReconciler(
        registry,
        accept_thresholds={
            CriticalityLevel.C0: 0.70,
            CriticalityLevel.C1: 0.80,
            CriticalityLevel.C2: 0.92,
            CriticalityLevel.C3: 0.98,
        },
    )
    # v11.4: shaped FORMAT_VALID + HARD_VALIDATION alone may use a 0.92 floor
    # (closes single-engine near-miss STP without inventing ink).
    format_relieved = reconciler.reconcile(
        "insured_id_number",
        [_candidate("135353652", "rapidocr", 0.99)],
        CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert format_relieved.decision == Decision.ACCEPT
    assert "FORMAT_VALID_ID_THRESHOLD_RELIEF" in format_relieved.rationale_codes or (
        "UNIQUE_SHAPED_ID_CORROBORATED" in format_relieved.rationale_codes
    )
    assert "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" not in format_relieved.rationale_codes

    # With member-relationship E6, near-miss confidence is corroboration-backed.
    result = reconciler.reconcile(
        "insured_id_number",
        [_candidate("135353652", "rapidocr", 0.99)],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "135353652"
    assert "IDENTITY_CORROBORATED_THRESHOLD_RELIEF" in result.rationale_codes
    assert "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" not in result.rationale_codes


def test_date_corroborated_threshold_relief_for_patient_dob():
    """Calendar-valid DOB near C2 floor accepts with DATE_VALID corroboration."""
    registry = CalibrationRegistry(
        {
            ("rapidocr", "patient_dob"): IsotonicCalibration(
                (0.0, 1.0), (0.88, 0.88), "dob-near-miss-v1"
            )
        }
    )
    reconciler = EvidenceReconciler(
        registry,
        accept_thresholds={
            CriticalityLevel.C0: 0.70,
            CriticalityLevel.C1: 0.80,
            CriticalityLevel.C2: 0.92,
            CriticalityLevel.C3: 0.98,
        },
    )
    blocked = reconciler.reconcile(
        "patient_dob",
        [_candidate("1993-03-31", "rapidocr", 0.75)],
        CriticalityLevel.C2,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert blocked.decision == Decision.ESCALATE
    assert "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" in blocked.rationale_codes

    result = reconciler.reconcile(
        "patient_dob",
        [_candidate("1993-03-31", "rapidocr", 0.75)],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "1993-03-31"
    assert (
        "DATE_CORROBORATED_THRESHOLD_RELIEF" in result.rationale_codes
        or "DATE_UNIQUE_CALENDAR_CORROBORATED" in result.rationale_codes
    )
    assert "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" not in result.rationale_codes



def test_conflict_margin_relieved_for_equivalent_member_id_padding():
    # Leading-zero padding normalizes to the same agreement key, so engines
    # support one canonical value (no CONFLICT_MARGIN_TOO_SMALL).
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate("0000374350", "paddleocr", 0.97),
            _candidate("00000374350", "rapidocr", 0.96),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes
    assert "MULTI_ENGINE_AGREEMENT" in result.rationale_codes


def test_conflict_margin_relieved_for_date_fragments_when_date_valid():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("1946-07-16", "paddleocr", 0.93),
            _candidate("07/16/1946", "rapidocr", 0.91),
            _candidate("MM DD", "tesseract", 0.90),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_dob_separator_artifact_relieved_even_with_large_margin():
    """CMS dashed rules → 01↔11; peel even when confidences are far apart."""
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("11/08/2018", "paddleocr", 0.99),
            _candidate("01/08/2018", "rapidocr", 0.80),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "01/08/2018"
    assert "DOB_SEPARATOR_ARTIFACT_RELIEVED" in result.rationale_codes
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_dob_separator_artifact_prefers_clean_day():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("01/19/1960", "paddleocr", 0.94),
            _candidate("01/09/1960", "rapidocr", 0.93),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "01/09/1960"
    assert "DOB_SEPARATOR_ARTIFACT_RELIEVED" in result.rationale_codes


def test_dob_separator_does_not_invent_unobserved_year_1179():
    """EJG7.013: compact ``05131179`` must not peel into invented ``1179-05-03``."""
    from packages.candidate_reconciliation.reconciler import (
        _dob_ymd,
        prefer_dob_without_separator_one,
    )

    assert _dob_ymd("05131179") is None
    assert prefer_dob_without_separator_one("05/13/1979", ["05131179"]) is None
    assert prefer_dob_without_separator_one("1979-05-13", ["05131179"]) is None

    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("05131179", "paddleocr", 0.89),
            _candidate("1979-05-13", "rapidocr", 0.87),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "1979-05-13"
    assert result.selected_value != "1179-05-03"
    assert "DOB_SEPARATOR_ARTIFACT_RELIEVED" not in result.rationale_codes


def test_dob_prefers_calendar_valid_over_header_label():
    result = EvidenceReconciler().reconcile(
        "patient_dob",
        [
            _candidate("MM", "paddleocr", 0.99),
            _candidate("01/03/2006", "rapidocr", 0.88),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "DATE_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "01/03/2006"
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_name_ji_insertion_equivalent_josephine():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("MARENCO JIOSEPHINE A", "paddleocr", 0.95),
            _candidate("MARENCO, JOSEPHINE A", "rapidocr", 0.94),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "JOSEPHINE" in (result.selected_value or "").upper()
    assert "JIOSEPHINE" not in (result.selected_value or "").upper()
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_name_confusable_insertion_reynele():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("REYNEL.1ISA", "paddleocr", 0.95),
            _candidate("REYNELLSA", "rapidocr", 0.94),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_name_label_contamination_relieved():
    result = EvidenceReconciler().reconcile(
        "insured_name",
        [
            _candidate("SLOGER CHLOE", "paddleocr", 0.97),
            _candidate(
                "4. 1NSURED'S NAME . FURST NAME SLOGER CHLOE",
                "rapidocr",
                0.99,
            ),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "SLOGER" in (result.selected_value or "").upper()
    assert "INSURED" not in (result.selected_value or "").upper()
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_name_token_prefix_expansion_relieved():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("ORR JAMES", "paddleocr", 0.94),
            _candidate("ORR JAMES ANTHONY", "rapidocr", 0.96),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "ANTHONY" in (result.selected_value or "").upper()
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_name_letter_substitution_equivalent():
    result = EvidenceReconciler().reconcile(
        "patient_name",
        [
            _candidate("OWENS CAITEIN", "paddleocr", 0.93),
            _candidate("OWENS, CAITLIN", "rapidocr", 0.97),
        ],
        CriticalityLevel.C2,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.decision == Decision.ACCEPT
    assert "CAITLIN" in (result.selected_value or "").upper().replace(" ", "")
    assert "CONFLICT_MARGIN_TOO_SMALL" not in result.rationale_codes


def test_shaped_member_id_preferred_over_header_crop():
    result = EvidenceReconciler().reconcile(
        "insured_id_number",
        [
            _candidate(
                "1a.INSURED'SI.D.NUMBER (ForPrograminItem1",
                "paddleocr",
                0.93,
            ),
            _candidate("20143064268", "rapidocr", 0.89),
        ],
        CriticalityLevel.C3,
        deterministic_evidence={
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "MEMBER_RELATIONSHIP_CONFIRMED",
        },
        document_family="CMS1500",
        enforce_legacy_evidence_policy=False,
    )
    assert result.selected_value == "20143064268"
    assert "INSURED" not in (result.selected_value or "").upper()
