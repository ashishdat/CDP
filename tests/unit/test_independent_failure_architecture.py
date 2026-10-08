import json
import threading
from pathlib import Path

import pytest

from packages.recovery.independent_failures import analyze_failure, classify_page_text
from scripts.annotate_independent_reg_classes import annotate_row
from scripts.audit_independent_failures import audit, latest_rows
from scripts.run_hackathon_1000_cascade import _append_ledger, _write_json


@pytest.mark.parametrize("text,expected", [
    ("", "EMPTY_OCR"), ("unidentified image", "UNKNOWN"),
    ("DOCUMENT SEPARATOR", "DOCUMENT_SEPARATOR"),
    ("Document Separator Unique ID", "UNIQUE_ID_COVER"),
    ("FAX IMAGE therefore better", "FAX_PATCH"),
    ("DOCUMENT SEPARATOR CMS-1500 NUCC", "CMS1500"),
    ("FAX IMAGE UB-04 CMS-1450", "UB04"),
    ("DOCUMENT SEPARATOR PATIENT NAME", "CLAIM_FORM"),
])
def test_claim_evidence_wins_over_cover_labels(text, expected):
    assert classify_page_text(text).value == expected


@pytest.mark.parametrize("text,available", [("", False), ("", True),
    ("CMS-1500", True), ("unidentified image", True), ("DOCUMENT SEPARATOR", True)])
def test_annotation_never_invents_irreducibility(text, available):
    row = {"claim_id": "synthetic", "disposition": "REGISTRATION_FAILED",
           "true_stp": False, "reg_resolution": "IRREDUCIBLE_NO_CLAIM_INK"}
    result = annotate_row(row, text, text_available=available)
    assert result["reg_resolution"] != "IRREDUCIBLE_NO_CLAIM_INK"
    assert result["disposition"] == row["disposition"]
    assert result["reg_class_evidence"]["verified_non_claim"] is False
    assert row["reg_resolution"] == "IRREDUCIBLE_NO_CLAIM_INK"


def test_empty_ocr_cannot_prove_missing_ink_or_nonclaim_page():
    result = analyze_failure({"disposition": "REGISTRATION_FAILED"}, page_text="")
    assert result["page_role_verified"] is False
    assert not any("NON_CLAIM" in x["mechanism"] for x in result["findings"])


def test_missing_page_text_is_unknown_not_an_empty_ocr_observation():
    result = analyze_failure({'disposition': 'HITL', 'registration_ok': False,
                              'registration_reason': 'NO_TEMPLATE_ABOVE_THRESHOLD'})
    assert result['page_role'] == 'UNKNOWN'
    assert result['page_text_available'] is False
    assert result['findings'][0]['mechanism'] == 'TEMPLATE_SELECTION_FALLBACK_REQUIRES_REVIEW'
    assert result['findings'][0]['stage'] == 'template_selection'


def test_unsafe_geometry_is_a_mechanism_not_a_proven_bad_scan():
    result = analyze_failure({"disposition": "REGISTRATION_FAILED",
                              "registration_reason": "low_inlier_ratio,unsafe_perspective_distortion"})
    assert {x["mechanism"] for x in result["findings"]} == {
        "INSUFFICIENT_SPATIAL_SUPPORT", "UNSAFE_TRANSFORM"}
    assert all(x["root_cause_status"] == "OBSERVED_MECHANISM_ONLY" for x in result["findings"])
    assert all(x["max_attempts"] <= 2 for x in result["findings"])


def test_missing_charge_corroboration_is_not_recovered_by_lowering_thresholds():
    row = {"disposition": "HITL", "critical_blockers": ["total_charge"], "fields": {
        "total_charge": {"value": "SENSITIVE", "reasons": ["LINE_TOTALS_UNCORROBORATED"]}}}
    result = analyze_failure(row)
    assert result["findings"][0]["mechanism"] == "MISSING_CORROBORATING_EVIDENCE"
    assert "ACQUIRE_BOX28_CROP_EVIDENCE" in result["findings"][0]["next_steps"]
    assert "SENSITIVE" not in json.dumps(result)
    assert result["cloud_execution_authorized"] is False
    assert row["disposition"] == "HITL"


def test_output_and_ledger_have_same_failure_analysis(tmp_path):
    row = {"finished": True, "claim_id": "synthetic", "disposition": "HITL",
           "critical_blockers": ["patient_dob"], "fields": {}}
    result = tmp_path / "result.json"
    ledger = tmp_path / "results.jsonl"
    _write_json(result, row)
    _append_ledger(ledger, row, threading.Lock())
    assert json.loads(result.read_text())["failure_analysis"] == json.loads(ledger.read_text())["failure_analysis"]
    assert "failure_analysis" not in row


def test_direct_digit_reader_observations_are_counted_and_unavailability_is_retained(tmp_path):
    from scripts.run_hackathon_1000_cascade import _ocr_engine_stats

    ocr = tmp_path / 'ocr'
    ocr.mkdir()
    attempts = [{'engine': e, 'reason': 'OBSERVED'} for e in ('paddleocr', 'rapidocr')]
    attempts += [{'engine': 'tesseract_digits', 'reason': 'PSM_7',
                  'observation': {'text': '1997'}},
                 {'engine': 'tesseract', 'reason': 'DOB_CONFIRM_PSM_8',
                  'observation': {'text': '12181997'}},
                 {'engine': 'tesseract', 'reason': 'DOB_CONFIRM_PSM_7',
                  'observation': {'text': ''}},
                 {'engine': 'tesseract_digits', 'reason': 'UNAVAILABLE'}]
    (ocr / 'OCRCandidates.json').write_text(json.dumps({'fields': [{'attempts': attempts}]}))
    stats = _ocr_engine_stats(tmp_path)
    assert stats['tesseract_observed'] == 2
    assert stats['tesseract_unavailable'] == 1
    assert stats['cascade_healthy'] is False


def test_fallback_text_is_preserved_with_hash_and_used_by_offline_audit(tmp_path):
    import hashlib
    from scripts.run_hackathon_1000_cascade import _save_unstructured_page_text

    root = tmp_path / 'run'
    claim = root / 'claims/synthetic'
    text = 'CMS-1500 NUCC patient name source observation'
    reference = _save_unstructured_page_text(claim, text)
    assert Path(reference['path']).read_text(encoding='utf-8') == text
    assert reference['sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert _save_unstructured_page_text(claim, None) is None
    row = {'claim_id': 'synthetic', 'finished': True, 'disposition': 'HITL',
           'critical_blockers': ['patient_dob']}
    (root / 'results.jsonl').write_text(json.dumps(row) + '\n')
    report = audit([root], tmp_path / 'audit.json')
    assert report['cases'][0]['analysis']['page_role'] == 'CMS1500'
    assert report['cases'][0]['analysis']['page_text_available'] is True
    assert text not in json.dumps(report)


def test_audit_latest_records_and_partial_append_without_changing_source(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    ledger = root / "results.jsonl"
    old = {"claim_id": "synthetic", "finished": True, "disposition": "REGISTRATION_FAILED"}
    new = {**old, "disposition": "TRUE_STP"}
    payload = json.dumps(old) + "\n" + json.dumps(new) + "\n" + '{"partial":'
    ledger.write_text(payload)
    rows, digest = latest_rows(ledger)
    assert rows == [new] and len(digest) == 64
    report = audit([root], tmp_path / "audit.json")
    assert report["cases"] == []
    assert report["cohorts"][0]["finished"] == 1
    assert ledger.read_text() == payload


def test_audit_exposes_premature_dob_stop_and_registration_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv('CDP_CLOUD_STOP_LADDER', '1')
    root = tmp_path / 'run'
    ocr = root / 'claims/synthetic/ocr'
    ocr.mkdir(parents=True)
    field = {'field': 'patient_dob', 'candidates': [
        {'engine': 'rapidocr', 'value': '05/15/2010'}],
        'cloud_stop_ladder': {'skipped': 'LOCALS_SETTLED'}}
    (ocr / 'OCRCandidates.json').write_text(json.dumps({'fields': [field]}))
    row = {'claim_id': 'synthetic', 'finished': True, 'completed': True,
           'disposition': 'HITL', 'registration_ok': False,
           'critical_blockers': ['patient_dob']}
    (root / 'results.jsonl').write_text(json.dumps(row) + '\n')
    (root / 'benchmark_runtime.json').write_text(json.dumps({'sample_size': 2}))
    report = audit([root], tmp_path / 'audit.json')
    cohort = report['cohorts'][0]
    assert cohort['pending'] == 1
    assert cohort['registration_fallback_hitl_count'] == 1
    assert cohort['premature_recorded_stops_by_field'] == {'patient_dob': 1}
    assert report['cases'][0]['acquisition_findings'][0]['premature_recorded_stop']
    assert '05/15/2010' not in json.dumps(report)


def test_benchmark_counts_registration_fallback_hitl_without_double_counting(tmp_path, monkeypatch):
    from scripts import benchmark_hackathon_four_corpora as benchmark
    import scripts.score_hackathon_gt_accuracy as scorer

    monkeypatch.setattr(benchmark, 'OUT', tmp_path)
    monkeypatch.setattr(scorer, 'score', lambda *args: {
        'field_count': 0, 'claims_scored': 0, 'false_accepts': 0})
    root = tmp_path / 'product/corpus_100'
    root.mkdir(parents=True)
    rows = [{'document': 'a', 'finished': True, 'completed': True,
             'true_stp': False, 'disposition': 'HITL', 'registration_ok': False},
            {'document': 'b', 'finished': True, 'completed': True,
             'true_stp': True, 'disposition': 'TRUE_STP', 'registration_ok': True}]
    (root / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    manifest = {'ground_truth_snapshot': str(tmp_path / 'absent.json'),
                'corpora': [{'pool_size': 100, 'sample_size': 3, 'documents': ['a', 'b', 'c']}]}
    report = benchmark.summarize(manifest, 'PRODUCT')
    assert report['overall']['registration_fallback_hitl_count'] == 1
    assert report['overall']['registration_failure_count'] == 0
    assert report['overall']['hitl_count'] == 1
    assert report['overall']['pending'] == 1


def test_audit_rejects_corruption_inside_ledger(tmp_path):
    ledger = tmp_path / "results.jsonl"
    ledger.write_text('not-json\n')
    with pytest.raises(json.JSONDecodeError):
        latest_rows(ledger)


@pytest.mark.parametrize("hint", [None, "", "AUTO"])
def test_unseen_pages_use_automatic_classification_on_both_execution_paths(hint):
    from pathlib import Path

    from scripts.run_hackathon_1000_cascade import _app_stage_command, _classification_hint

    assert _classification_hint(hint) is None
    command = _app_stage_command(Path("dataset.yaml"), "synthetic", Path("out"), hint)
    assert "--document-type" not in command


def test_explicit_operator_hint_is_preserved():
    from pathlib import Path

    from scripts.run_hackathon_1000_cascade import _app_stage_command, _classification_hint

    assert _classification_hint("UB04") == "UB04"
    command = _app_stage_command(Path("dataset.yaml"), "synthetic", Path("out"), "UB04")
    assert command[-2:] == ["--document-type", "UB04"]
    with pytest.raises(ValueError):
        _classification_hint("guessed-family")


def test_resuming_old_or_changed_policies_cannot_mix_metrics(tmp_path):
    from packages.recovery.independent_failures import validate_resume_contract

    contract = {"classification_mode": "AUTO", "policy": "v2"}
    ledger = tmp_path / "results.jsonl"
    ledger.write_text('{"old": true}\n')
    with pytest.raises(ValueError, match="fresh output directory"):
        validate_resume_contract(tmp_path, contract, resume=True)
    assert ledger.read_text() == '{"old": true}\n'
    with pytest.raises(ValueError, match="fresh output directory"):
        validate_resume_contract(tmp_path, contract, resume=False)
    fresh = tmp_path / "fresh"
    validate_resume_contract(fresh, contract, resume=False)
    (fresh / "results.jsonl").write_text('{"current": true}\n')
    validate_resume_contract(fresh, contract, resume=True)
    with pytest.raises(ValueError, match="classification changed"):
        validate_resume_contract(fresh, {**contract, "classification_mode": "CMS1500"}, resume=True)
    assert ledger.read_text() == '{"old": true}\n'
