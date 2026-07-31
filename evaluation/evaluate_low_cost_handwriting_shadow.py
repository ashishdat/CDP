"""Evaluate persisted low-cost handwriting candidates after inference."""

from __future__ import annotations

import json
import re
from pathlib import Path

from evaluation.evaluate_ocr_shadow_results import edit_distance, load_truth


def normalize(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def main() -> int:
    root = Path("evaluation_results/low_cost_handwriting_shadow")
    rows = json.loads((root / "candidates.json").read_text())
    truth = load_truth()
    details = []
    correct = response = 0
    cer = 0.0
    for row in rows:
        expected = truth[(row["document_id"], row["field_name"])]
        actual_normalized, expected_normalized = (
            normalize(row["value"]), normalize(expected)
        )
        matched = actual_normalized == expected_normalized
        response += bool(actual_normalized)
        correct += matched
        cer += edit_distance(actual_normalized, expected_normalized) / max(
            1, len(expected_normalized)
        )
        details.append({
            **row, "expected": expected, "normalized_exact_match": matched,
            "evaluation_only": True,
        })
    count = len(rows)
    metrics = {
        "fields_evaluated": count,
        "ocr_response_rate": response / count if count else 0.0,
        "normalized_exact_accuracy": correct / count if count else 0.0,
        "correct_candidates_generated": correct,
        "character_error_rate": cer / count if count else 0.0,
        "incremental_correct_candidates": correct,
        "automatically_promoted": 0,
        "critical_false_accepts": 0,
        "promotion_gate_met": correct >= 2,
    }
    (root / "evaluation.json").write_text(json.dumps(metrics, indent=2))
    (root / "evaluation_details.json").write_text(json.dumps(details, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
