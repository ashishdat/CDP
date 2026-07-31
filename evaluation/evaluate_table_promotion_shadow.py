"""Evaluate promotable table routes without changing production authority."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def main() -> int:
    details = json.loads(
        Path("evaluation_results/reporting_v3/details.json").read_text(encoding="utf-8")
    )
    policy = yaml.safe_load(
        Path("config/evaluation/table_promotion_v3.yaml").read_text(encoding="utf-8")
    )
    table = [
        row for row in details
        if row["field_identity"]["service_line_number"] is not None
    ]
    eligible = []
    for row in table:
        evidence = set(row["validation_results"])
        is_blank = "SEMANTIC_BLANK_EVIDENCE" in evidence
        cross_family = "CROSS_FAMILY_AGREEMENT" in evidence
        type_allowed = row["expected_data_type"] in policy["promotable_nonblank_types"]
        if is_blank or (cross_family and type_allowed):
            eligible.append(row)
    report = {
        "policy_version": policy["policy_version"],
        "policy_status": policy["status"],
        "fields_evaluated": len(table),
        "shadow_promotion_eligible": len(eligible),
        "shadow_promotion_correct": sum(row["selected_correct"] for row in eligible),
        "shadow_promotion_incorrect": sum(not row["selected_correct"] for row in eligible),
        "shadow_selective_accuracy": (
            sum(row["selected_correct"] for row in eligible) / len(eligible)
            if eligible else None
        ),
        "critical_false_accepts": sum(
            row["criticality"] == "CRITICAL" and not row["selected_correct"]
            for row in eligible
        ),
        "actually_promoted": 0,
        "promotion_blocker": "NO_UNTOUCHED_HOLDOUT_AVAILABLE",
        "candidate_authority": "REVIEW_ONLY",
    }
    output = Path("evaluation_results/reporting_v3/table_promotion_shadow.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
