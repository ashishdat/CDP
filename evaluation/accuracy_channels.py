"""Publish automated, reference-blocked and human-verified accuracy channels."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    automated = json.loads(Path("evaluation_results/current_v2_router/metrics.json").read_text())
    pareto = json.loads(
        Path("evaluation_results/remaining_error_pareto/metrics.json").read_text()
    )
    categories = pareto["by_category"]
    decisions = json.loads(
        Path("evaluation_results/current_v2_router/details.json").read_text()
    )
    shadow_path = Path(
        "evaluation_results/ocr_shadow_bakeoff/evaluation/metrics.json"
    )
    shadow = json.loads(shadow_path.read_text()) if shadow_path.is_file() else {}
    handwriting_path = Path(
        "evaluation_results/low_cost_handwriting_shadow/evaluation.json"
    )
    handwriting = (
        json.loads(handwriting_path.read_text())
        if handwriting_path.is_file() else {}
    )
    total = automated["evaluated_visible_fields"]
    reference_blocked = categories["REFERENCE_BLOCKED"]
    review_required = categories["UNREADABLE_REQUIRES_REVIEW"]
    semantic_review = categories["GROUND_TRUTH_OUTPUT_SEMANTIC_DISAGREEMENT"]
    derived_review = sum(
        row["reason"] == "REVIEW_ONLY_CROSS_FIELD_DERIVATION" for row in decisions
    )
    correct = round(total * automated["extraction_accuracy"])
    automatically_accepted = sum(not row["review_required"] for row in decisions)
    automatically_accepted_correct = sum(
        not row["review_required"] and row["extraction_correct"] for row in decisions
    )
    automatically_accepted_incorrect = sum(
        not row["review_required"] and not row["extraction_correct"] for row in decisions
    )
    abstained = total - automatically_accepted
    report = {
        "PRODUCTION_AUTOMATED_ACCURACY": automated["extraction_accuracy"],
        "SHADOW_CANDIDATE_CEILING": (
            min(total, correct + int(shadow.get("union_correct_candidates", 0))) / total
        ),
        "SAFELY_PROMOTED_AUTOMATED_ACCURACY": None,
        "REFERENCE_VERIFIED_ACCURACY": None,
        "LOW_COST_HANDWRITING_FIELDS_EVALUATED": handwriting.get(
            "fields_evaluated", 0
        ),
        "LOW_COST_HANDWRITING_INCREMENTAL_CORRECT": handwriting.get(
            "incremental_correct_candidates", 0
        ),
        "LOW_COST_HANDWRITING_PROMOTED": handwriting.get(
            "automatically_promoted", 0
        ),
        "AUTOMATED_EXTRACTION_ACCURACY": automated["extraction_accuracy"],
        "EXTRACTION_CORRECT_FIELDS": correct,
        "TOTAL_EVALUATED_FIELDS": total,
        "VISIBLE_FIELD_DENOMINATOR": total,
        "AUTOMATICALLY_ELIGIBLE_FIELDS": automatically_accepted,
        "AUTOMATICALLY_ACCEPTED_FIELDS": automatically_accepted,
        "AUTOMATICALLY_CORRECT_FIELDS": automatically_accepted_correct,
        "AUTOMATICALLY_INCORRECT_FIELDS": automatically_accepted_incorrect,
        "AUTOMATED_ACCURACY": automatically_accepted_correct / total,
        "AUTOMATED_ELIGIBLE_FIELD_ACCURACY": (
            automatically_accepted_correct / automatically_accepted
            if automatically_accepted else None
        ),
        "AUTOMATED_COVERAGE": automatically_accepted / total,
        "ABSTAINED_FIELDS": abstained,
        "ABSTENTION_RATE": abstained / total,
        "REVIEW_RATE": (review_required + derived_review) / total,
        "REFERENCE_BLOCKED_RATE": reference_blocked / total,
        "REFERENCE_BLOCKED_FIELDS": reference_blocked,
        "HUMAN_REVIEW_REQUIRED_FIELDS": review_required + derived_review,
        "UNREADABLE_REVIEW_FIELDS": review_required,
        "DERIVED_REVIEW_ONLY_FIELDS": derived_review,
        "SEMANTIC_REVIEW_FIELDS": semantic_review,
        "HUMAN_VERIFIED_FINAL_ACCURACY": None,
        "FINAL_VALIDATED_ACCURACY": None,
        "human_verified_status": "NO_APPROVED_REVIEW_COMPLETIONS_AVAILABLE",
        "unverified_handwritten_critical_review_rate": 1.0,
        "INCORRECTLY_AUTOMATED_FIELDS": automatically_accepted_incorrect,
        "critical_false_accepts": automated["critical_false_accepts"],
        "policy_version": "extraction-v2",
        "denominator_note": (
            "Extraction accuracy measures candidate correctness over all visible fields. "
            "Automated accuracy and coverage count only fields accepted without review. "
            "Every channel publishes its denominator."
        ),
    }
    output = Path("evaluation_results/accuracy_channels.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
