"""Evaluation-only mismatch taxonomy and Pareto remediation report."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from evaluation.matcher import match_fields
from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset, PredictionDataset

CATEGORIES = (
    "Wrong page selected",
    "Wrong document family",
    "Alignment/crop error",
    "Printed OCR error",
    "Handwriting-recognition error",
    "Name/address parsing error",
    "Missing reference-data match",
    "Incorrect candidate selection",
    "Ground-truth or output-semantic mismatch",
    "Truly unreadable field",
)

REMEDIATIONS = {
    "Wrong page selected": "score every page per required field",
    "Wrong document family": "improve family anchors/classifier",
    "Alignment/crop error": "recalibrate local alignment and field padding",
    "Printed OCR error": "fine-tune printed recognizer or add independent OCR",
    "Handwriting-recognition error": "review, label and fine-tune field-family model",
    "Name/address parsing error": "correct semantic parser and reading order",
    "Missing reference-data match": "integrate authorized versioned reference adapter",
    "Incorrect candidate selection": "calibrate/reweight reconciliation evidence",
    "Ground-truth or output-semantic mismatch": "resolve output contract semantics",
    "Truly unreadable field": "human verification",
}


@dataclass(frozen=True)
class BacklogItem:
    document_id: str
    form_type: str
    field_name: str
    category: str
    critical: bool
    family: str | None
    expected: str | None
    actual: str | None
    remediation: str


def classify(pair, expected: str, actual: str) -> str:
    prediction = pair.prediction
    metadata = prediction.metadata if prediction else {}
    field = pair.truth.field_name
    if prediction is None or not actual:
        if pair.document.form_type == "UNSTRUCTURED" and not metadata.get("routed_page"):
            return "Wrong page selected"
        return "Alignment/crop error"
    if metadata.get("document_family") == "UNKNOWN":
        return "Wrong document family"
    if field in {"patient_first", "patient_last"} and metadata.get(
        "authoritative_reference_match"
    ) is not True:
        if sorted(expected.split()) == sorted(actual.split()) or len(expected) != len(actual):
            return "Name/address parsing error"
        return "Missing reference-data match"
    if (
        "addr" in field or field in {"patient_city", "insured_city"}
    ) and sorted(expected.split()) == sorted(actual.split()):
        return "Name/address parsing error"
    writing = metadata.get("writing_type")
    if writing in {"HANDWRITTEN", "MIXED"}:
        return "Handwriting-recognition error"
    candidates = metadata.get("ocr_candidates", [])
    if any(str(candidate.get("value") or "") == expected for candidate in candidates):
        return "Incorrect candidate selection"
    if prediction.crop_reference and not metadata.get("alignment_score", 1):
        return "Alignment/crop error"
    if prediction.extraction_method == "OPENCV_ALIGNED_PADDLEOCR" and (
        pair.document.form_type == "UNSTRUCTURED"
    ):
        return "Wrong page selected"
    return "Printed OCR error"


def build_backlog(
    truth: GroundTruthDataset,
    predictions: PredictionDataset,
    registry: NormalizerRegistry,
) -> list[BacklogItem]:
    items = []
    for pair in match_fields(truth, predictions):
        expected = pair.truth.expected_normalized
        if expected is None:
            expected = registry.normalize(pair.truth.field_name, pair.truth.expected_raw)
        actual = pair.prediction.normalized_value if pair.prediction else None
        if actual is None:
            actual = registry.normalize(
                pair.truth.field_name,
                pair.prediction.raw_value if pair.prediction else None,
            )
        if (expected or "") == (actual or ""):
            continue
        category = classify(pair, expected or "", actual or "")
        family = (
            pair.prediction.metadata.get("document_family")
            if pair.prediction else None
        )
        items.append(BacklogItem(
            pair.document.document_id, pair.document.form_type,
            pair.truth.field_name, category, pair.truth.critical, family,
            expected, actual, REMEDIATIONS[category],
        ))
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation_results/error_backlog")
    )
    args = parser.parse_args()
    truth = GroundTruthDataset.model_validate_json(
        args.ground_truth.read_text(encoding="utf-8")
    )
    predictions = PredictionDataset.model_validate_json(
        args.predictions.read_text(encoding="utf-8")
    )
    registry = NormalizerRegistry.from_yaml(
        Path("config/evaluation/normalization_rules.yaml")
    )
    items = build_backlog(truth, predictions, registry)
    counts = Counter(item.category for item in items)
    families: dict[str, set[str]] = defaultdict(set)
    critical = Counter()
    for item in items:
        families[item.category].add(item.family or item.form_type)
        critical[item.category] += item.critical
    total = len(items)
    pareto = [
        {
            "category": category,
            "failed_fields": count,
            "percentage_of_errors": count / total if total else 0,
            "affected_families": sorted(families[category]),
            "affected_critical_fields": critical[category],
            "expected_remediation": REMEDIATIONS[category],
        }
        for category, count in counts.most_common()
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "pareto.json").write_text(
        json.dumps({"total_errors": total, "pareto": pareto}, indent=2),
        encoding="utf-8",
    )
    (args.output / "items.json").write_text(
        json.dumps([asdict(item) for item in items], indent=2), encoding="utf-8"
    )
    rows = "".join(
        f"<tr><td>{html.escape(row['category'])}</td><td>{row['failed_fields']}</td>"
        f"<td>{row['percentage_of_errors']:.1%}</td>"
        f"<td>{html.escape(', '.join(row['affected_families']))}</td>"
        f"<td>{row['affected_critical_fields']}</td>"
        f"<td>{html.escape(row['expected_remediation'])}</td></tr>"
        for row in pareto
    )
    (args.output / "pareto.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>OCR error Pareto</title>"
        "<style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:8px;text-align:left}</style>"
        f"<h1>OCR error-reduction backlog</h1><p>Total mismatches: {total}</p>"
        "<table><tr><th>Failure category</th><th>Failed fields</th><th>% errors</th>"
        "<th>Families</th><th>Critical</th><th>Expected remediation</th></tr>"
        f"{rows}</table>",
        encoding="utf-8",
    )
    print(json.dumps({"total_errors": total, "pareto": pareto[:5]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
