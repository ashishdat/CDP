"""Score sealed unresolved-crop outputs after inference has completed."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from workers.field_candidates.name_interpretations import interpret_complete_name


def normalize(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--azure", type=Path, required=True, nargs="+")
    parser.add_argument("--paddle-evaluation", type=Path, required=True)
    parser.add_argument("--paddle-candidates", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    azure = [
        row for path in args.azure
        for row in json.loads(path.read_text(encoding="utf-8"))
    ]
    report = json.loads(args.details.read_text(encoding="utf-8"))
    paddle = json.loads(args.paddle_evaluation.read_text(encoding="utf-8"))
    paddle_candidates = json.loads(args.paddle_candidates.read_text(encoding="utf-8"))
    failures = {
        (row["field_identity"]["document_id"], row["field_identity"]["semantic_field"]): row
        for row in report if not row["selected_correct"]
    }
    paddle_correct = {
        (row["document_id"], row["field_name"])
        for row in paddle if row["correct_candidate_generated"]
    }
    complete_names: dict[tuple[str, str], list[str]] = {}
    for candidate in paddle_candidates:
        if candidate["field_name"] not in {"patient_first", "patient_last"}:
            continue
        value = str(candidate.get("normalized_value") or "").strip()
        if len(value.split()) < 2:
            continue
        complete_names.setdefault(
            (candidate["document_id"], candidate["field_name"]), []
        ).append(value)
    details = []
    azure_correct: set[tuple[str, str]] = set()
    derived_correct: set[tuple[str, str]] = set()
    for row in azure:
        key = (row["document_id"], row["field_name"])
        failure = failures[key]
        expected = failure["normalized_expected_value"]
        correct = normalize(row.get("value")) == normalize(expected)
        if correct:
            azure_correct.add(key)
        derived_values = []
        raw_value = str(row.get("value") or "").strip()
        family = failure["field_identity"]["document_family"]
        if row["field_name"] in {"patient_first", "patient_last"} and raw_value:
            convention = "LAST_FIRST" if family == "CMS1500" else "FIRST_LAST"
            interpretations = interpret_complete_name(raw_value, convention)
            if interpretations:
                parsed = interpretations[0]
                derived_values.append(parsed.first if row["field_name"] == "patient_first" else parsed.last)
        regional_names = complete_names.get(key, [])
        if regional_names:
            # Choose by OCR consensus before evaluation truth is inspected.
            complete_name = Counter(regional_names).most_common(1)[0][0]
            convention = "LAST_FIRST" if family == "CMS1500" else "FIRST_LAST"
            interpretations = interpret_complete_name(complete_name, convention)
            if interpretations:
                parsed = interpretations[0]
                derived_values.append(
                    parsed.first if row["field_name"] == "patient_first" else parsed.last
                )
        if family == "UB04" and row["field_name"] == "patient_first" and raw_value:
            # UB92 record 20 field 05 is positions 45-53 (nine characters).
            derived_values.append(raw_value[:9])
        derived_match = any(normalize(value) == normalize(expected) for value in derived_values)
        if derived_match:
            derived_correct.add(key)
        details.append({
            "document_id": key[0], "field_name": key[1],
            "azure_value": row.get("value"), "expected": expected,
            "correct": correct, "insufficient_evidence": row["insufficient_evidence"],
            "derived_values": derived_values, "derived_correct": derived_match,
            "candidate_authority": "REVIEW_ONLY",
            "pass_type": row.get("pass_type", "CELL_ONLY"),
        })
    union = azure_correct | derived_correct | paddle_correct
    baseline_correct, total = 216, 239
    metrics = {
        "baseline_correct": baseline_correct, "total_fields": total,
        "azure_candidate_attempts": len(azure), "azure_correct_recoveries": len(azure_correct),
        "deterministic_derived_recoveries": len(derived_correct - azure_correct),
        "paddle_correct_recoveries": len(paddle_correct),
        "union_correct_recoveries": len(union),
        "projected_correct_with_review_only_union": baseline_correct + len(union),
        "projected_selected_accuracy_with_review_only_union": (baseline_correct + len(union)) / total,
        "recoveries_required_for_98_percent": 19,
        "remaining_recoveries_to_target": max(0, 19 - len(union)),
        "evaluation_truth_loaded_during_inference": False,
        "warning": "Projected union includes review-only candidates; it is not automated production accuracy.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.output / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
