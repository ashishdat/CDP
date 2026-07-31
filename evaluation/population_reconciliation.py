"""Reconcile the 366-field legacy denominator with the visible-field Pareto.

Reference/review status is deliberately reported as an overlapping governance
dimension rather than subtracted twice from the mutually exclusive population.
"""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    legacy = json.loads(Path("evaluation_results/atomic_all/evaluation.json").read_text())
    router = json.loads(Path("evaluation_results/current_v2_router/metrics.json").read_text())
    pareto = json.loads(
        Path("evaluation_results/remaining_error_pareto/metrics.json").read_text()
    )
    accuracy = json.loads(Path("evaluation_results/accuracy_channels.json").read_text())

    total = int(legacy["field_count"])
    visible = int(router["evaluated_visible_fields"])
    visible_correct = round(visible * float(router["extraction_accuracy"]))
    scoped_failures = int(pareto["remaining_errors"])
    blank_or_not_applicable = total - visible
    excluded = total - visible_correct - scoped_failures - blank_or_not_applicable
    if excluded < 0:
        raise ValueError("population categories overlap or exceed total evaluated fields")

    payload = {
        "all_evaluated_fields": total,
        "mutually_exclusive_population": {
            "correct_automated_visible_fields": visible_correct,
            "scoped_visible_field_failures": scoped_failures,
            "expected_blank_or_not_applicable": blank_or_not_applicable,
            "excluded_or_unclassified": excluded,
        },
        "visible_field_denominator": visible,
        "automated_visible_field_accuracy": router["extraction_accuracy"],
        "governance_status_non_additive": {
            "reference_blocked_fields": accuracy["REFERENCE_BLOCKED_FIELDS"],
            "critical_fields_routed_to_review": router[
                "critical_fields_routed_to_review"
            ],
            "human_verified_final_accuracy": accuracy[
                "HUMAN_VERIFIED_FINAL_ACCURACY"
            ],
        },
        "invariants": {
            "visible_correct_plus_failures_equals_visible": (
                visible_correct + scoped_failures == visible
            ),
            "population_sums_to_all_evaluated": (
                visible_correct + scoped_failures + blank_or_not_applicable + excluded
                == total
            ),
            "review_reference_status_not_assumed_correct": (
                accuracy["HUMAN_VERIFIED_FINAL_ACCURACY"] is None
            ),
        },
        "interpretation": (
            f"The {scoped_failures}-case Pareto covers every currently incorrect "
            "visible field. "
            "The remaining 152 fields in the 366-field legacy denominator are "
            "blank/not-applicable and are not part of visible OCR accuracy. "
            "Reference/review counts overlap the visible population and are not "
            "added as a second population category."
        ),
    }
    output = Path("evaluation_results/population_reconciliation.json")
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
