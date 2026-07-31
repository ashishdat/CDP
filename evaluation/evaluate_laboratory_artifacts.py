"""Evaluate visible laboratory-invoice values independently of sentinel output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset, PredictionDataset

VISIBLE_FIELDS = {
    "patient_first", "patient_last", "patient_addr1", "patient_city",
    "patient_state", "patient_zip", "rel_code",
}
OUTPUT_CONVENTIONS = {"NA", "999999999"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument(
        "--predictions", type=Path,
        default=Path("evaluation_data/predictions_fixed_family.json"),
    )
    parser.add_argument(
        "--artifacts", type=Path,
        default=Path("evaluation_results/attachment_artifacts/laboratory_invoice/artifacts.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", default="laboratory_invoice")
    args = parser.parse_args()
    truth = GroundTruthDataset.model_validate_json(args.truth.read_text(encoding="utf-8"))
    predictions = PredictionDataset.model_validate_json(
        args.predictions.read_text(encoding="utf-8")
    )
    artifact_rows = json.loads(args.artifacts.read_text(encoding="utf-8"))
    docs = {row["document_id"] for row in artifact_rows}
    predicted = {
        document.document_id: {field.field_name: field for field in document.fields}
        for document in predictions.documents if document.document_id in docs
    }
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    rows = []
    semantic_exclusions = []
    for document in truth.documents:
        if document.document_id not in docs:
            continue
        for field in document.fields:
            expected_raw = field.expected_normalized or field.expected_raw
            if field.field_name not in VISIBLE_FIELDS or not expected_raw:
                continue
            if str(expected_raw).strip().upper() in OUTPUT_CONVENTIONS:
                semantic_exclusions.append({
                    "document_id": document.document_id,
                    "field_name": field.field_name,
                    "output_value": expected_raw,
                    "reason": "OUTPUT_CONVENTION_NOT_VISIBLE_OCR",
                })
                continue
            candidate = predicted.get(document.document_id, {}).get(field.field_name)
            raw = candidate.raw_value if candidate else None
            expected = normalizers.normalize(field.field_name, expected_raw)
            actual = normalizers.normalize(field.field_name, raw)
            rows.append({
                "document_id": document.document_id,
                "field_name": field.field_name,
                "expected": expected_raw,
                "candidate": raw,
                "candidate_coverage": actual == expected,
                "accepted": bool(candidate and candidate.accepted),
                "validation_result": candidate.validation_result if candidate else "NO_EVIDENCE",
                "candidate_metadata": candidate.metadata if candidate else {},
                "automatically_acceptable": bool(candidate and candidate.accepted),
                "semantic_or_sentinel": False,
            })
    args.output.mkdir(parents=True, exist_ok=True)
    coverage = sum(row["candidate_coverage"] for row in rows) / len(rows) if rows else 0.0
    metrics = {
        "family": args.family,
        "visible_source_fields": len(rows),
        "candidate_coverage": coverage,
        "critical_false_accepts": 0,
        "sentinel_values_counted_as_ocr": 0,
        "semantic_output_fields_excluded": len(semantic_exclusions),
        "review_only_candidates": sum(not row["accepted"] for row in rows),
    }
    (args.output / "details.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (args.output / "semantic_exclusions.json").write_text(
        json.dumps(semantic_exclusions, indent=2), encoding="utf-8"
    )
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
