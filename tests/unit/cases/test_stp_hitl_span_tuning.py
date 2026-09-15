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
