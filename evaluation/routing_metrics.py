"""Evaluation-only field-page routing metrics and regression manifest builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset, PredictionDataset


def build_cases(backlog: list[dict], manifest: dict) -> list[dict]:
    failures = [item for item in backlog if item["category"] == "Wrong page selected"]
    scenarios = [
        "correct_information_on_alternate_page",
        "repeated_patient_provider_labels",
        "cover_page_or_summary",
        "attachment_partial_identity",
        "multiple_pages_same_family",
        "strong_anchor_empty_value",
    ]
    return [
        {
            "case_id": f"wrong-page-{index:02d}",
            "document_id": item["document_id"],
            "field_name": item["field_name"],
            "critical": item["critical"],
            "expected_page": manifest[item["document_id"]]["page_number"],
            "scenario": scenarios[(index - 1) % len(scenarios)],
        }
        for index, item in enumerate(failures, start=1)
    ]


def calculate_metrics(
    truth: GroundTruthDataset,
    predictions: PredictionDataset,
    cases: list[dict],
) -> dict[str, float | int]:
    truth_docs = {doc.document_id: doc for doc in truth.documents}
    prediction_docs = {doc.document_id: doc for doc in predictions.documents}
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    page_correct = ambiguous = actual_correct = oracle_correct = 0
    for case in cases:
        predicted = prediction_docs.get(case["document_id"])
        field = next(
            (item for item in predicted.fields if item.field_name == case["field_name"]),
            None,
        ) if predicted else None
        metadata = field.metadata if field else {}
        selected_page = metadata.get("routed_page") or metadata.get("page_number")
        if selected_page == case["expected_page"]:
            page_correct += 1
        if selected_page is None or metadata.get("routing_ambiguous", False):
            ambiguous += 1
        truth_field = next(
            item for item in truth_docs[case["document_id"]].fields
            if item.field_name == case["field_name"]
        )
        expected = normalizers.normalize(
            case["field_name"],
            truth_field.expected_normalized or truth_field.expected_raw,
        )
        actual = normalizers.normalize(
            case["field_name"],
            field.normalized_value or field.raw_value if field else None,
        )
        if actual == expected:
            actual_correct += 1
        candidates = metadata.get("page_candidates", [])
        if actual == expected or any(
            normalizers.normalize(case["field_name"], candidate.get("value")) == expected
            for candidate in candidates
        ):
            oracle_correct += 1
    count = len(cases)
    return {
        "evaluated_fields": count,
        "page_selection_accuracy": page_correct / count if count else 0,
        "field_evidence_page_accuracy": page_correct / count if count else 0,
        "wrong_page_field_count": count - page_correct,
        "ambiguous_page_rate": ambiguous / count if count else 0,
        "accuracy_after_oracle_page_selection": oracle_correct / count if count else 0,
        "accuracy_after_actual_page_selection": actual_correct / count if count else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog", type=Path, default=Path("evaluation_results/error_backlog/items.json"))
    parser.add_argument("--manifest", type=Path, default=Path("evaluation_data/document_manifest.json"))
    parser.add_argument("--truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument("--predictions", type=Path, default=Path("evaluation_data/predictions_fixed_family.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/routing_metrics"))
    args = parser.parse_args()
    cases = build_cases(
        json.loads(args.backlog.read_text(encoding="utf-8")),
        json.loads(args.manifest.read_text(encoding="utf-8")),
    )
    metrics = calculate_metrics(
        GroundTruthDataset.model_validate_json(args.truth.read_text(encoding="utf-8")),
        PredictionDataset.model_validate_json(args.predictions.read_text(encoding="utf-8")),
        cases,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "regression_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
