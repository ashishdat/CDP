from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.generate_production_report import _evaluate
from evaluation.reporting_v3_common import (
    assert_unique,
    contract_checksum,
    ratio,
    sha256_file,
)

ROOT = next(parent for parent in Path(__file__).parents if (parent / "pyproject.toml").exists())


def _load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_v2_recalculation_is_from_source_rows():
    metrics = _load("evaluation_results/reporting_v3/metrics.json")["extraction_v2"]
    assert metrics["eligible_fields"] == 214
    assert metrics["correct_selected_values"] == 191
    assert metrics["extraction_accuracy"] == 191 / 214


def test_expanded_contract_has_239_unique_eligible_fields():
    contract = _load("evaluation_data/contracts/evaluation_contract_v3.json")
    assert contract["eligible_field_count"] == 239
    assert_unique(contract["fields"])


def test_table_review_only_is_excluded_from_automation():
    metrics = _load("evaluation_results/reporting_v3/metrics.json")
    assert metrics["table_only"]["automatically_accepted_candidates"] == 0
    assert metrics["expanded_v3"]["automatically_accepted_fields"] == 125


def test_invalid_repeated_labels_and_unused_rows_are_excluded():
    quality = _load("evaluation_results/reporting_v3/data_quality.json")
    assert quality["invalid_repeated_labels_excluded"] == 5
    assert quality["unused_rows_included"] == 0
    assert quality["eligible_table_labels"] == 25


def test_active_blank_cells_are_not_automatic_successes():
    details = _load("evaluation_results/reporting_v3/details.json")
    blanks = [
        row for row in details
        if row["field_identity"]["service_line_number"] is not None
        and row["normalized_expected_value"] == ""
    ]
    assert blanks
    assert all(row["candidate_status"] != "AUTO_ACCEPTED" for row in blanks)


def test_null_denominator_returns_null():
    assert ratio(0, 0) is None


def test_critical_false_accept_is_calculated_dynamically():
    metrics = _load("evaluation_results/reporting_v3/metrics.json")["expanded_v3"]
    assert metrics["critical_false_accepts"] == (
        metrics["critical_fields_incorrectly_accepted"]
    )


def test_potential_and_final_accuracy_are_separate():
    metrics = _load("evaluation_results/reporting_v3/metrics.json")["expanded_v3"]
    assert metrics["potential_accuracy_after_successful_review"] is not None
    assert metrics["final_validated_accuracy"] is None
    assert metrics["final_validated_status"] == "UNAVAILABLE_PENDING_REVIEW"


def test_contract_checksum_and_sidecar_match():
    contract = _load("evaluation_data/contracts/evaluation_contract_v3.json")
    assert contract_checksum(contract) == contract["contract_sha256"]
    sidecar = (
        ROOT / "evaluation_data/contracts/evaluation_contract_v3.sha256"
    ).read_text().strip()
    assert sidecar == contract["contract_sha256"]


def test_prediction_checksum_matches_manifest():
    manifest = _load("evaluation_results/predictions_v3/inference_manifest.json")
    assert sha256_file(
        ROOT / "evaluation_results/predictions_v3/predictions.json"
    ) == manifest["prediction_artifact_sha256"]


def test_inference_runner_has_no_truth_or_label_access():
    source = (ROOT / "evaluation/run_production_contract.py").read_text().lower()
    forbidden = (
        "evaluation_data", "approved_cell_labels", "ground_truth.json",
        "expected_value", "normalized_expected_value",
    )
    assert not [token for token in forbidden if token in source]


def test_duplicate_identity_rejected():
    field = {"field_identity": {
        "document_id": "x", "page_number": 1, "document_family": "x",
        "form_version": "1", "form_locator": "1", "service_line_number": 1,
        "semantic_field": "x",
    }}
    with pytest.raises(ValueError, match="duplicate"):
        assert_unique([field, field])


def test_all_expanded_details_have_provenance():
    details = _load("evaluation_results/reporting_v3/details.json")
    assert len(details) == 239
    assert all(row["provenance"] for row in details)


def test_report_metrics_equal_details():
    details = _load("evaluation_results/reporting_v3/details.json")
    metrics = _load("evaluation_results/reporting_v3/metrics.json")["expanded_v3"]
    assert metrics["correct_selected_values"] == sum(
        row["selected_correct"] for row in details
    )
    assert metrics["automatically_accepted_fields"] == sum(
        row["candidate_status"] == "AUTO_ACCEPTED" for row in details
    )


def test_reporting_modules_have_no_hardcoded_accuracy_constants():
    quality = _load("evaluation_results/reporting_v3/data_quality.json")
    assert quality["hardcoded_metric_hits"] == []


def test_acceptance_gate_and_changed_denominator_warning():
    gate = _load("evaluation_results/reporting_v3/acceptance_gate.json")
    report = (ROOT / "evaluation_results/reporting_v3/comparison.html").read_text()
    assert gate["passed"] is True
    assert "denominators differ" in report
    assert "not automated production accuracy" in report


def test_review_only_correct_does_not_increase_automated_accuracy():
    contract = {
        "fields": [{
            "field_identity": {
                "document_id": "x", "page_number": 1, "document_family": "x",
                "form_version": "1", "form_locator": "1", "service_line_number": 1,
                "semantic_field": "code",
            },
            "eligibility_status": "ELIGIBLE", "criticality": "NONCRITICAL",
            "expected_data_type": "code",
        }]
    }
    prediction = [{
        "field_identity": contract["fields"][0]["field_identity"],
        "selected_value": "A", "normalized_value": "A",
        "candidate_status": "REVIEW_ONLY", "review_required": True,
        "provider": "shadow", "provider_version": "1", "confidence": 1.0,
        "validation_results": [], "crop_quality": "VALID_SINGLE_CELL",
        "row_status": "ACTIVE", "provenance": {"raw_candidates": []},
        "automatically_acceptable": False,
    }]
    label = [{
        "field_identity": contract["fields"][0]["field_identity"],
        "expected_value": "A", "normalized_expected_value": "A",
        "approval_status": "APPROVED",
    }]
    metrics, _ = _evaluate(contract, prediction, label)
    assert metrics["extraction_accuracy"] == 1.0
    assert metrics["automated_accuracy_over_all_fields"] == 0.0
    assert metrics["automatically_accepted_fields"] == 0
