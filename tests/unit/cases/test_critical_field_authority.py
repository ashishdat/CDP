"""Authorized critical-field reference authority — STP94 safe path."""

from __future__ import annotations

import json
from pathlib import Path

from packages.reference_enrichment.critical_field_authority import (
    lookup_authorized_reference,
    resolve_critical_field,
)


def _ref(**kwargs):
    base = {
        "member_id": "97739518",
        "authorized": True,
        "identity_verified": True,
        "effective_from": "2020-01-01",
        "version": "intake-v1",
        "patient_dob": "1980-01-01",
        "patient_name": "CMUNAULANI AIALL",
        "insured_name": "CMUNAULANI AIALL",
        "source": "AUTHORIZED_INTAKE",
    }
    base.update(kwargs)
    return base


def test_authorized_effective_reference_accepts_dob():
    result = resolve_critical_field(
        field="patient_dob",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="97739518",
        reference=_ref(),
        document_date="2024-06-01",
    )
    assert result.disposition == "AUTO_ACCEPTED"
    assert result.value == "1980-01-01"
    assert result.evidence_type == "AUTHORIZED_REFERENCE"
    assert result.reason == "EXACT_ID_AUTHORIZED_REFERENCE"
    assert result.metadata["member_id"] == "97739518"
    assert result.metadata["reference_version"] == "intake-v1"
    assert result.metadata["effective_from"] == "2020-01-01"


def test_mismatched_id_escalates():
    result = resolve_critical_field(
        field="patient_dob",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="00000000",
        reference=_ref(),
        document_date="2024-06-01",
    )
    assert result.disposition == "ESCALATE"
    assert result.reason == "REFERENCE_ID_MISMATCH"


def test_absent_authorized_flag_escalates():
    result = resolve_critical_field(
        field="patient_name",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="97739518",
        reference=_ref(authorized=False),
        document_date="2024-06-01",
    )
    assert result.disposition == "ESCALATE"
    assert result.reason == "REFERENCE_NOT_AUTHORIZED"


def test_reference_effective_after_document_date_escalates():
    result = resolve_critical_field(
        field="patient_dob",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="97739518",
        reference=_ref(effective_from="2025-01-01"),
        document_date="2024-06-01",
    )
    assert result.disposition == "ESCALATE"
    assert result.reason == "REFERENCE_NOT_EFFECTIVE"


def test_missing_field_escalates():
    result = resolve_critical_field(
        field="patient_dob",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="97739518",
        reference=_ref(patient_dob=None),
        document_date="2024-06-01",
    )
    assert result.disposition == "ESCALATE"
    assert result.reason == "REFERENCE_FIELD_MISSING"


def test_ocr_auto_remains_unchanged():
    result = resolve_critical_field(
        field="patient_dob",
        ocr_value="1990-02-02",
        ocr_auto=True,
        verified_member_id="97739518",
        reference=_ref(),
        document_date="2024-06-01",
    )
    assert result.disposition == "AUTO_ACCEPTED"
    assert result.value == "1990-02-02"
    assert result.evidence_type == "INDEPENDENT_OCR"
    assert result.reason == "OCR_AUTHORITY"


def test_total_charge_cannot_be_filled_from_reference():
    result = resolve_critical_field(
        field="total_charge",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="97739518",
        reference=_ref(total_charge="400.00"),
        document_date="2024-06-01",
    )
    assert result.disposition == "ESCALATE"
    assert result.reason == "REFERENCE_FORBIDDEN_FOR_TOTAL_CHARGE"
    assert result.value is None


def test_no_environment_index_returns_abstain(monkeypatch):
    monkeypatch.delenv("CDP_AUTHORIZED_MEMBER_INDEX", raising=False)
    assert lookup_authorized_reference("97739518") is None
    result = resolve_critical_field(
        field="patient_name",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="97739518",
        reference=None,
        document_date="2024-06-01",
    )
    assert result.disposition == "ESCALATE"
    assert result.reason == "NO_AUTHORIZED_REFERENCE"


def test_accepted_reference_carries_audit_metadata(tmp_path: Path, monkeypatch):
    index = tmp_path / "members.json"
    index.write_text(
        json.dumps(
            {
                "members": {
                    "97739518": {
                        "authorized": True,
                        "identity_verified": True,
                        "effective_from": "2019-05-01",
                        "version": "intake-v2",
                        "patient_dob": "1980-01-01",
                        "source": "AUTHORIZED_INTAKE",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CDP_AUTHORIZED_MEMBER_INDEX", str(index))
    reference = lookup_authorized_reference("97739518")
    assert reference is not None
    assert reference["member_id"] == "97739518"
    result = resolve_critical_field(
        field="patient_dob",
        ocr_value="",
        ocr_auto=False,
        verified_member_id="97739518",
        reference=reference,
        document_date="2024-01-01",
    )
    assert result.disposition == "AUTO_ACCEPTED"
    assert result.metadata["member_id"] == "97739518"
    assert result.metadata["reference_version"] == "intake-v2"
    assert result.metadata["effective_from"] == "2019-05-01"
    assert result.metadata["field"] == "patient_dob"


def test_identity_not_verified_escalates():
    result = resolve_critical_field(
        field="insured_name",
        ocr_value=None,
        ocr_auto=False,
        verified_member_id="97739518",
        reference=_ref(identity_verified=False),
        document_date="2024-06-01",
    )
    assert result.disposition == "ESCALATE"
    assert result.reason == "REFERENCE_IDENTITY_NOT_VERIFIED"
