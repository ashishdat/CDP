"""CLI: python -m evaluation.runner --ground-truth ... --predictions ..."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.metrics import evaluate
from evaluation.normalizers import NormalizerRegistry
from evaluation.reports import write_reports
from evaluation.schemas import GroundTruthDataset, PredictionDataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate field-level claim extraction")
    parser.add_argument("--dataset", type=Path, help="Source dataset root (provenance only)")
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--normalization-rules", type=Path, default=Path("config/evaluation/normalization_rules.yaml"))
    parser.add_argument("--split", choices=["calibration", "validation", "holdout"])
    args = parser.parse_args()
    truth = GroundTruthDataset.model_validate_json(args.ground_truth.read_text(encoding="utf-8"))
    if args.split:
        truth = truth.model_copy(update={"documents": [d for d in truth.documents if d.split == args.split]})
    predictions = PredictionDataset.model_validate_json(args.predictions.read_text(encoding="utf-8"))
    registry = NormalizerRegistry.from_yaml(args.normalization_rules)
    metrics = evaluate(truth, predictions, registry)
    write_reports(metrics, args.output)
    print(json.dumps({
        "documents": len(truth.documents),
        "fields": metrics.field_count,
        "normalized_accuracy": metrics.normalized_field_accuracy,
        "critical_false_accept_rate": metrics.critical_false_accept_rate,
        "perfect_claim_rate": metrics.perfect_claim_rate,
        "stp_rate": metrics.straight_through_processing_rate,
        "output": str(args.output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
