"""Evaluate the first 50 approved table labels and publish the decision gate."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.evaluate_table_shadow import evaluate


def main() -> int:
    metrics, _ = evaluate()
    count = metrics["approved_labeled_candidates"]
    accuracy = metrics["normalized_cell_accuracy"]
    recovered = metrics["newly_recovered_production_fields"]
    if count < 50:
        decision = "AWAIT_FIRST_50_APPROVED_LABELS"
    elif accuracy >= 0.95 and recovered > 0:
        decision = "CONTINUE_TO_150"
    elif accuracy >= 0.85:
        decision = "IMPROVE_FAMILY_GRID_OR_NORMALIZATION"
    elif recovered == 0:
        decision = "REPORT_EVIDENCE_ONLY"
    else:
        decision = "RESTRICT_TO_SUCCESSFUL_FAMILIES"
    payload = {
        "approved_labels": count,
        "checkpoint_size": 50,
        "normalized_accuracy": accuracy,
        "new_fields_recovered": recovered,
        "decision": decision,
        "production_accuracy": 0.8925233644859814,
        "production_modifications": 0,
        "critical_false_accepts": metrics["critical_false_accepts"],
    }
    output = Path("evaluation_results/table_shadow_v2/checkpoint_50.json")
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
