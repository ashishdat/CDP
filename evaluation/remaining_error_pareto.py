"""Classify remaining extraction errors without feeding truth into inference."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def main() -> int:
    decisions = {
        (row["document_id"], row["field_name"]): row
        for row in json.loads(Path("evaluation_results/current_v2_router/details.json").read_text())
    }
    sources = []
    for path in (
        Path("evaluation_results/structured_rollout/cms1500/details.json"),
        Path("evaluation_results/structured_rollout/ub04/details.json"),
    ):
        sources.extend(json.loads(path.read_text()))
    for family in ("laboratory_invoice", "statement", "psychological_receipt", "cms_attachment"):
        sources.extend(json.loads(
            Path(f"evaluation_results/attachment_rollout/{family}/details.json").read_text()
        ))
    rows = []
    for source in sources:
        key = (source["document_id"], source["field_name"])
        decision = decisions.get(key)
        if not decision or decision["extraction_correct"]:
            continue
        covered = source.get("candidate_coverage", False)
        raw_candidates = source.get("all_candidates", [])
        expected = str(source.get("expected") or "").upper()
        raw_contains_expected = any(
            expected and expected in " ".join(map(str, candidate.get("raw", []))).upper()
            for candidate in raw_candidates
        )
        validations = {
            result
            for candidate in raw_candidates
            for result in candidate.get("validation_results", [])
            if str(candidate.get("normalized") or "").upper() == expected
        }
        if expected in {"UNKNOWN", "NA", "N/A"}:
            category = "GROUND_TRUTH_OUTPUT_SEMANTIC_DISAGREEMENT"
        elif (
            key[1] in {"patient_first", "patient_last"}
            and decision["reason"] == "REFERENCE_REQUIRED"
        ):
            category = "REFERENCE_BLOCKED"
        elif "fixed_width_output_projection" in validations:
            category = "FIXED_WIDTH_OUTPUT_PROJECTION_FAILURE"
        elif validations and validations <= {"NEEDS_REVIEW"}:
            category = "UNREADABLE_REQUIRES_REVIEW"
        elif covered:
            category = "CORRECT_CANDIDATE_GENERATED_NOT_SELECTED"
        elif raw_contains_expected:
            category = "CORRECT_TEXT_WRONG_COMPONENT_PARSE"
        elif decision["reason"] in {
            "NO_VALID_VALUE", "BELOW_THRESHOLD", "BELOW_VALUE_THRESHOLD",
            "INSUFFICIENT_EVIDENCE",
        }:
            category = "UNREADABLE_REQUIRES_REVIEW"
        else:
            category = "CORRECT_CANDIDATE_NOT_GENERATED"
        rows.append({
            "document_id": key[0], "field_name": key[1],
            "document_family": source.get("form_type", "attachment"),
            "provider_adapter": sorted({
                item.get("provider", "unknown") for item in raw_candidates
            }) or ["unknown"],
            "writing_type": source.get("writing_type", "UNKNOWN"),
            "criticality": (
                "CRITICAL" if key[1] in {
                    "patient_first", "patient_last", "patient_dob",
                    "insured_member_id", "provider_npi", "principal_diagnosis",
                } else "NON_CRITICAL"
            ),
            "crop_quality": "AVAILABLE_NOT_CALIBRATED" if source.get("crop_valid") else "UNKNOWN",
            "error_category": category,
            "reference_verification": "UNAVAILABLE",
            "semantic_output_projection_failure": False,
            "review_required": decision["review_required"],
        })
    category_counts = Counter(row["error_category"] for row in rows)
    metrics = {
        "remaining_errors": len(rows),
        "by_category": {
            category: category_counts.get(category, 0)
            for category in (
                "CORRECT_CANDIDATE_GENERATED_NOT_SELECTED",
                "CORRECT_CANDIDATE_NOT_GENERATED",
                "CORRECT_TEXT_WRONG_COMPONENT_PARSE",
                "SEMANTIC_STATE_FAILURE",
                "FIXED_WIDTH_OUTPUT_PROJECTION_FAILURE",
                "REFERENCE_BLOCKED",
                "UNREADABLE_REQUIRES_REVIEW",
                "GROUND_TRUTH_OUTPUT_SEMANTIC_DISAGREEMENT",
            )
        },
        "by_field": dict(Counter(row["field_name"] for row in rows).most_common()),
        "by_family": dict(Counter(row["document_family"] for row in rows).most_common()),
        "reference_verification_unavailable": sum(
            row["reference_verification"] == "UNAVAILABLE" for row in rows
        ),
    }
    output = Path("evaluation_results/remaining_error_pareto")
    output.mkdir(parents=True, exist_ok=True)
    (output / "details.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
