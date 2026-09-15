"""STP/HITL tuning: CMS-1500 span cleanup and weak-E4 opt-out."""

from __future__ import annotations

from pathlib import Path

from packages.criticality import CriticalityLevel
from packages.evidence.models import EvidenceBundle, EvidenceClass, EvidenceItem
from packages.evidence.policy import EvidencePolicy
from packages.extraction_recovery.span_selection import select_field_span


def test_cms1500_name_span_strips_box_header_and_keeps_last_first():
    selected = select_field_span(
        "2. PATIENT'S NAME (Last Name, First Name, Middle lnitial)\nCAMARATO, JOSHUA",
        "PERSON_NAME",
        "patient_name",
    )
    assert selected.selected_text == "CAMARATO, JOSHUA"


def test_cms1500_member_id_span_extracts_trailing_identifier():
    selected = select_field_span(
        "1a. INSURED'S ID, NUMBER\n(For Program in Item 1)\n993751319",
        "ALPHANUMERIC_ID",
        "insured_id_number",
    )
    assert selected.selected_text == "993751319"


def test_cms1500_dob_token_assembly_and_rejects_garbage():
    ok = select_field_span(
        "3. PATIENT'S BIRTH DATE\nMM\nDD\nYY\n1\n4\n20\nM",
        "DATE",
        "patient_dob",
    )
    assert ok.selected_text == "01/04/2020"
    bad = select_field_span(
        "3. PATIENT'S BIATH DATE\n68\n11990\nM",
        "DATE",
        "patient_dob",
    )
    assert "19/90" not in bad.selected_text


def test_currency_npi_bleed_yields_empty_for_hitl():
    selected = select_field_span("L\nNPI", "CURRENCY", "total_charge")
    assert selected.selected_text == ""
    assert "NPI_LABEL_BLEED" in selected.reason_codes


def test_patient_name_policy_allows_weak_e4_when_configured():
    policy = EvidencePolicy.load(Path("config/evidence_policies.yaml"))
    bundle = EvidenceBundle(
        field_name="patient_name",
        evidence_items=(
            EvidenceItem(
                evidence_class=EvidenceClass.E1,
                evidence_type="OCR_EXTRACTION",
                evidence_family="ocr",
                source="rapidocr",
                value="CAMARATO, JOSHUA",
            ),
            EvidenceItem(
                evidence_class=EvidenceClass.E3,
                evidence_type="TEMPLATE_REGISTRATION_CONFIRMED",
                evidence_family="registration",
                source="geometry",
                value="ok",
                metadata={"field_specific": True},
            ),
            EvidenceItem(
                evidence_class=EvidenceClass.E4,
                evidence_type="FORMAT_VALID",
                evidence_family="deterministic",
                source="validation",
                value="CAMARATO, JOSHUA",
                metadata={"strength": "WEAK"},
            ),
        ),
    )
    ok, available, missing, reasons = policy.evaluate(
        "patient_name", CriticalityLevel.C2, bundle, document_family="CMS1500"
    )
    assert ok, (available, missing, reasons)
    assert "E4" in available


def test_roi_insets_shrink_dob_and_charge_windows():
    from packages.extraction_recovery.roi_insets import inset_bbox
    dob = inset_bbox((667, 402, 886, 459), "patient_dob")
    assert dob[1] > 402  # top inset removes header band
    assert dob[2] < 886  # right inset clears sex checkbox
    charge = inset_bbox((1280, 1750, 1470, 1811), "total_charge")
    assert charge[0] > 1280  # left inset clears NPI legend bleed


def test_currency_rejects_npi_adjacent_one_dollar_artifact():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("1\nNPI", "CURRENCY", "total_charge")
    assert selected.selected_text == ""
    assert "NPI_LABEL_BLEED" in selected.reason_codes


def test_claim_total_e6_from_service_lines():
    from packages.claim_evidence.builder import ClaimEvidenceBuilder
    result = ClaimEvidenceBuilder.load().build(
        claim_id="c1",
        document_family="CMS1500",
        claim_values={"total_charge": "30.00"},
        service_lines=[{"charges": "20.00"}, {"charges": "10.00"}],
    )
    assert "CLAIM_TOTAL_CONFIRMED" in {i.evidence_type for i in result.evidence_items}


def test_dob_assembles_when_year_token_is_middle():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("112\n11970\n05", "DATE", "patient_dob")
    assert selected.selected_text == "12/05/1970"


def test_currency_rejects_non_digit_glyph_crop():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("一", "CURRENCY", "total_charge")
    assert selected.selected_text == ""


def test_dob_assembles_dd_yyyy_mm_token_order():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("29\n1983\n10", "DATE", "patient_dob")
    assert selected.selected_text == "10/29/1983"


def test_currency_repairs_p_separator_to_cents():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("2084P080", "CURRENCY", "total_charge")
    assert selected.selected_text == "2084.80"


def test_currency_rejects_leading_minus_total_as_form_artifact():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("-2084P080", "CURRENCY", "total_charge")
    assert selected.selected_text == ""
    assert "CURRENCY_LEADING_MINUS" in selected.reason_codes


def test_currency_accepts_whole_dollar_service_line_charges():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("225", "CURRENCY", "charges")
    assert selected.selected_text == "225.00"


def test_name_span_strips_header_before_label_phrases():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span(
        "2.PATIENTS NAME(Lasi Name,First Name,MiddleInitial)\nDOLIET\nMARGARET M",
        "PERSON_NAME",
        "patient_name",
    )
    assert selected.selected_text == "DOLIET MARGARET M"


def test_member_id_repairs_ocr_zero_and_equals():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span(
        "1a.INSURED'S LD. NUMBER\n(For Program in ltem 1)\n0SC74765420",
        "ALPHANUMERIC_ID",
        "insured_id_number",
    )
    assert selected.selected_text == "OSC74765420"
    selected2 = select_field_span(
        "1a. INSURED'S I.D. NUM8ER\n(For Program in ltem 1)\nNALC\nP32=84957",
        "ALPHANUMERIC_ID",
        "insured_id_number",
    )
    assert selected2.selected_text == "P32-84957"


def test_dob_assembles_when_year_has_trailing_period():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("29\n1983\n10.", "DATE", "patient_dob")
    assert selected.selected_text == "10/29/1983"

def test_dob_assembles_cjk_confusable_digit_stream():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("04 1 了 .9 9 1 1", "DATE", "patient_dob")
    assert selected.selected_text == "04/17/1991"


def test_insured_name_prefers_ink_below_header_boilerplate():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span(
        "4. INSURED'S NAME (Last NaTe, First NaTe, Midale Inilial)\n2\nMCQUEEN, VASHONDA",
        "PERSON_NAME",
        "insured_name",
    )
    assert selected.selected_text == "MCQUEEN, VASHONDA"


def test_insured_name_route_authority_present():
    from pathlib import Path
    from packages.route_registry.registry import RouteRegistry
    route = RouteRegistry.load(Path("config/ocr_field_routes.yaml")).find(
        "insured_name", "CMS1500", mode="runtime"
    )
    assert route is not None
    assert route.status.value == "PRODUCTION_APPROVED"

def test_dob_assembles_trailing_letter_bleed_and_three_digit_year():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("12 26l 108", "DATE", "patient_dob")
    assert selected.selected_text == "12/26/2008"


def test_dob_rejects_impossible_calendar_day():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("11 31 93", "DATE", "patient_dob")
    assert selected.selected_text != "11/31/1993"
    assert "11/31" not in selected.selected_text


def test_currency_repairs_i_slash_zero_zero_handwritten_charge():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("I/00", "CURRENCY", "charges")
    assert selected.selected_text == "100.00"
    assert "CURRENCY_CONFUSABLE_REPAIRED" in selected.reason_codes


def test_currency_repairs_l00_confusable_charge():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("L00", "CURRENCY", "charges")
    assert selected.selected_text == "100.00"


def test_dob_repairs_three_digit_year_missing_century_one():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("03 19 983", "DATE", "patient_dob")
    assert selected.selected_text == "03/19/1983"


def test_dob_merges_split_day_around_century_repaired_year():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("03 1 983 1 9 7 1", "DATE", "patient_dob")
    assert selected.selected_text == "03/19/1983"


def test_dob_does_not_merge_day_when_year_already_four_digits():
    from packages.extraction_recovery.span_selection import select_field_span
    selected = select_field_span("12 2 1983 6", "DATE", "patient_dob")
    assert selected.selected_text == "12/02/1983"
