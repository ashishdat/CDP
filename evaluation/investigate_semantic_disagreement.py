"""Classify semantic disagreements for specification/business adjudication."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    pareto = json.loads(
        Path("evaluation_results/remaining_error_pareto/details.json").read_text()
    )
    cases = []
    for row in pareto:
        if row["error_category"] != "GROUND_TRUTH_OUTPUT_SEMANTIC_DISAGREEMENT":
            continue
        cases.append({
            "document_id": row["document_id"],
            "field_name": row["field_name"],
            "classification_options": [
                "VISIBLE_VALUE_VS_OUTPUT_SENTINEL",
                "BLANK_VS_NOT_APPLICABLE",
                "SAME_AS_PATIENT_OR_INSURED",
                "OUTPUT_PROJECTION_RULE",
                "GROUND_TRUTH_MAPPING_INCONSISTENCY",
                "GENUINE_EXTRACTION_ERROR",
            ],
            "current_classification": "SPECIFICATION_REVIEW_REQUIRED",
            "decision": "HUMAN_REVIEW_REQUIRED",
            "automatic_acceptance": False,
            "required_authority": "APPROVED_NSF_UB92_RULE_OR_BUSINESS_OWNER",
        })
    output = Path("evaluation_results/semantic_review")
    output.mkdir(parents=True, exist_ok=True)
    (output / "details.json").write_text(json.dumps(cases, indent=2))
    metrics = {
        "semantic_cases": len(cases),
        "resolved_by_approved_rule": 0,
        "pending_specification_review": len(cases),
        "evaluation_specific_rules_added": 0,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
