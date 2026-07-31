"""Evaluate a labeled holdout only after frozen inference artifacts exist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def calculate_gate(rows: list[dict], policy: dict, reviewer_cost: float) -> dict:
    total = len(rows)
    selected = [row for row in rows if row["azure_selected"]]
    correct = sum(row["azure_correct"] for row in selected)
    invalid = [row for row in rows if row["crop_condition"] == "INVALID"]
    invalid_abstained = sum(row["azure_abstained"] for row in invalid)
    recovered = sum(
        not row["ocr_correct"] and row["azure_correct"] for row in rows
    )
    critical_false = sum(
        row["criticality"] == "CRITICAL"
        and row["azure_selected"] and not row["azure_correct"]
        for row in rows
    )
    avoided_reviews = sum(row["review_avoided"] for row in rows)
    cost = sum(float(row["azure_cost_usd"]) for row in rows)
    selective = correct / len(selected) if selected else None
    invalid_rate = invalid_abstained / len(invalid) if invalid else None
    provenance = sum(bool(row["provenance_complete"]) for row in rows) / total if total else None
    cost_per_avoided = cost / avoided_reviews if avoided_reviews else None
    gate = policy["promotion_gate"]
    checks = {
        "minimum_eligible_fields": total >= policy["holdout"]["minimum_eligible_fields"],
        "selective_accuracy": selective is not None and selective >= gate["selective_accuracy_minimum"],
        "critical_false_accepts": critical_false <= gate["critical_false_accepts_maximum"],
        "invalid_crop_abstention": invalid_rate is not None and invalid_rate >= gate["invalid_crop_abstention_minimum"],
        "provenance_completeness": provenance is not None and provenance >= gate["provenance_completeness_minimum"],
        "ground_truth_leakage": sum(row["leakage_violation"] for row in rows) <= gate["leakage_violations_maximum"],
        "incremental_recovery": recovered > gate["incremental_recovery_minimum_exclusive"],
        "no_extraction_v2_regression": sum(row["v2_regression"] for row in rows) <= gate["extraction_v2_regressions_maximum"],
        "cost_below_reviewer": cost_per_avoided is not None and cost_per_avoided < reviewer_cost,
        "new_documents_only": all(row["new_document"] for row in rows),
        "inference_before_labeling": all(row["inference_before_labeling"] for row in rows),
    }
    return {
        "passed": all(checks.values()), "checks": checks,
        "metrics": {
            "eligible_fields": total, "selective_accuracy": selective,
            "correct_abstention_rate": sum(row["azure_abstained"] and row["should_abstain"] for row in rows) / total if total else None,
            "invalid_crop_abstention_rate": invalid_rate,
            "confident_incorrect_responses": sum(row["azure_confident"] and not row["azure_correct"] for row in rows),
            "incremental_recovery_over_ocr": recovered,
            "critical_false_accepts": critical_false,
            "reviews_avoided": avoided_reviews, "review_reduction": avoided_reviews / total if total else None,
            "azure_cost_usd": cost,
            "cost_per_avoided_review_usd": cost_per_avoided,
            "latency_ms_per_recovered_field": sum(row["azure_latency_ms"] for row in rows) / recovered if recovered else None,
            "provenance_completeness": provenance,
        },
        "promotion_scope": "FIELD_FAMILY_ROUTE_ONLY",
        "canary_fraction": policy["rollout"]["initial_canary_fraction"],
        "rollback_required": policy["rollout"]["immediate_rollback_required"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewer-cost-usd", type=float, required=True)
    args = parser.parse_args()
    policy = yaml.safe_load(Path(
        "config/evaluation/azure_promotion_freeze.yaml"
    ).read_text(encoding="utf-8"))
    rows = json.loads(args.rows.read_text(encoding="utf-8"))
    report = calculate_gate(rows, policy, args.reviewer_cost_usd)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
