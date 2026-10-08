import hashlib
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from packages.extraction_recovery import unstructured_reg_fallback as fallback
from packages.extraction_recovery.independent_case_router import promote_unstructured_fields
from scripts.annotate_independent_reg_classes import write_annotations
from scripts.audit_independent_failures import latest_rows
from scripts.run_hackathon_1000_cascade import _independent_run_contract


@pytest.mark.parametrize("complete", [False, True])
def test_confirmation_strings_do_not_authorize_stp(complete):
    fields = {"patient_name": "SYNTHETIC PERSON"}
    critical = {"patient_name", "patient_dob", "insured_id_number", "total_charge"}
    if complete:
        fields.update(patient_dob="01/01/1970", insured_id_number="12345678", total_charge="10.00")
    reasons = dict.fromkeys(critical, "UNSTRUCTURED_CROSS_SOURCE_CONFIRMED")
    disposition, blockers = promote_unstructured_fields(fields, reasons)
    assert disposition == "HITL"
    assert set(blockers) == critical


@pytest.mark.parametrize("other", ["JOHN, SMITH", "SMITH, JOHN JOHN", "SMITH JOHN"])
def test_name_agreement_preserves_identity(other):
    assert not fallback._fields_agree("patient_name", "SMITH, JOHN", other)
    assert fallback._fields_agree("patient_name", "Smith, John", "SMITH,  JOHN")


def test_local_dob_is_not_confirmed_by_another_local_read(monkeypatch):
    from packages import azure_di_contracts
    from packages.recovery import azure_di_meter

    monkeypatch.setenv("CDP_UNSTRUCTURED_REG_FALLBACK", "1")
    monkeypatch.setattr(azure_di_contracts, "azure_document_intelligence_configured", lambda cfg: True)
    backend = SimpleNamespace(analyze_raw=lambda data: {"analyzeResult": {"content": "CMS-1500"}})
    monkeypatch.setattr(azure_di_contracts, "build_azure_read_engine", lambda cfg: SimpleNamespace(_backend=backend))
    monkeypatch.setattr(azure_di_meter, "record_azure_di_call", lambda **kw: None)
    monkeypatch.setattr(fallback, "_agent_should_run", lambda fields: False)
    monkeypatch.setattr(fallback, "_heuristic_fields_from_di_text",
                        lambda text: {"patient_dob": "01/01/1970"} if text == "LOCAL" else {})
    monkeypatch.setattr(fallback, "_dob_from_local_box3", lambda image: "01/01/1970")
    monkeypatch.setattr(fallback, "_local_ocr_full_page_text", lambda image: "LOCAL")
    monkeypatch.setattr(fallback, "_local_ocr_cms_box1a_text", lambda image: "")
    monkeypatch.setattr(fallback, "_local_ocr_cms_box28_text", lambda image: "")
    result = fallback.run_unstructured_reg_fallback(Image.new("RGB", (100, 100)), settings=SimpleNamespace())
    assert result.fields["patient_dob"] == "01/01/1970"
    assert result.field_reasons["patient_dob"] == "UNSTRUCTURED_LOCAL_SHAPED"


def test_annotation_snapshot_preserves_partial_ledger_and_newer_result(tmp_path):
    ledger = tmp_path / "results.jsonl"
    old = {"claim_id": "synthetic", "disposition": "REGISTRATION_FAILED"}
    payload = json.dumps(old) + '\n{"partial":'
    ledger.write_text(payload, encoding="utf-8")
    rows, digest = latest_rows(ledger)
    result = tmp_path / "result.json"
    result.write_text('{"disposition":"TRUE_STP"}', encoding="utf-8")
    target = write_annotations(tmp_path, rows, digest)
    assert ledger.read_text(encoding="utf-8") == payload
    assert json.loads(result.read_text())["disposition"] == "TRUE_STP"
    snapshot = json.loads(target.read_text())
    assert snapshot["ledger_sha256"] == hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert snapshot["operational_authority"] is False


def test_resume_contract_covers_acceptance_dependencies(tmp_path):
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("synthetic: true\n")
    hashes = _independent_run_contract(dataset, "AUTO", {})["component_sha256"]
    assert {"packages/claim_decision/service.py", "packages/claim_decision/contracts.py",
            "packages/evidence/builder.py", "packages/candidate_reconciliation/reconciler.py",
            "packages/extraction_recovery/unstructured_reg_fallback.py",
            "scripts/complete_from_extraction.py", "scripts/ocr_from_geometry.py"} <= hashes.keys()
