"""Evaluate completed candidate provenance; never imported by runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    truth = GroundTruthDataset.model_validate_json(
        args.truth.read_text(encoding="utf-8")
    )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    summary = {
        item["evaluation_document_id"]: item
        for item in json.loads(
            (args.candidates / "summary.json").read_text(encoding="utf-8")
        )
    }
    normalizers = NormalizerRegistry.from_yaml(
        "config/evaluation/normalization_rules.yaml"
    )
    totals = {
        "fields": 0, "candidate_covered": 0, "oracle_page_correct": 0,
        "actual_page_correct": 0, "extraction_correct": 0, "routing_ready": 0,
    }
    details = []
    for document in truth.documents:
        runtime_id = summary[document.document_id]["runtime_document_id"]
        root = args.candidates / runtime_id
        candidates = json.loads((root / "candidates.json").read_text(encoding="utf-8"))
        completeness = {
            row["field_name"]: row
            for row in json.loads((root / "completeness.json").read_text(encoding="utf-8"))
        }
        routing = {
            row["field_name"]: row
            for row in json.loads((root / "routing.json").read_text(encoding="utf-8"))
        }
        expected_page = manifest[document.document_id]["page_number"]
        for field in document.fields:
            expected = normalizers.normalize(
                field.field_name, field.expected_normalized or field.expected_raw
            )
            field_candidates = [
                row for row in candidates
                if row["field_name"] == field.field_name and row["status"] == "EVIDENCE"
            ]
            correct = [
                row for row in field_candidates
                if normalizers.normalize(field.field_name, row["normalized_value"]) == expected
            ]
            route = routing[field.field_name]
            selected_correct = (
                normalizers.normalize(field.field_name, route["selected_value"]) == expected
            )
            covered = bool(correct)
            oracle_page = any(row["page_number"] == expected_page for row in correct)
            actual_page = route["selected_page"] == expected_page
            extraction = actual_page and selected_correct
            totals["fields"] += 1
            totals["candidate_covered"] += covered
            totals["oracle_page_correct"] += oracle_page
            totals["actual_page_correct"] += actual_page
            totals["extraction_correct"] += extraction
            totals["routing_ready"] += completeness[field.field_name]["routing_ready"]
            details.append({
                "document_id": document.document_id,
                "field_name": field.field_name,
                "candidate_covered": covered,
                "oracle_page_correct": oracle_page,
                "actual_page_correct": actual_page,
                "extraction_correct": extraction,
                "routing_ready": completeness[field.field_name]["routing_ready"],
            })
    count = totals["fields"]
    metrics = {
        "evaluated_fields": count,
        "candidate_provenance_coverage": totals["routing_ready"] / count,
        "candidate_coverage": totals["candidate_covered"] / count,
        "oracle_page_accuracy": totals["oracle_page_correct"] / count,
        "actual_page_accuracy": totals["actual_page_correct"] / count,
        "extraction_accuracy": totals["extraction_correct"] / count,
        "wrong_page_field_count": count - totals["actual_page_correct"],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.output / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
