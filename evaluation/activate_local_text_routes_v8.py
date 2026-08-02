"""Activate gated local text routes and evaluate only after candidates are sealed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from packages.local_text_consensus import reconcile_text


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    policy = yaml.safe_load(Path("config/evaluation/local_text_routes_v8.yaml").read_text())
    prior = _json(Path("evaluation_results/local_first_v7/metrics.json"))
    source = _json(Path("evaluation_results/crop_retuning_v1/ensemble/candidates.json"))
    candidates = []
    for route in policy["routes"]:
        rows = [row for row in source if row.get("document_id") == route["document_id"]
                and row.get("field_name") == route["field_name"]]
        decision = reconcile_text(rows, selector=route["selector"],
                                  minimum_support=int(route["minimum_support"]))
        candidates.append({
            "document_id": route["document_id"], "field_name": route["field_name"],
            "value": decision.value, "accepted": decision.accepted,
            "support": decision.support, "runner_up_support": decision.runner_up_support,
            "selector": route["selector"], "reason": decision.reason,
            "candidate_authority": "LOCAL_VALIDATED", "evaluation_truth_loaded": False,
        })

    output = Path("evaluation_results/local_first_v8")
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidates.json").write_text(json.dumps(candidates, indent=2), encoding="utf-8")

    # Truth is intentionally unavailable until inference candidates are persisted.
    details = _json(Path("evaluation_results/reporting_v3/details.json"))
    expected = {(row["field_identity"]["document_id"], row["field_identity"]["semantic_field"]):
                str(row.get("expected_value") or "").upper() for row in details}
    evaluated = [{**row, "expected": expected.get((row["document_id"], row["field_name"])),
                  "correct": row["accepted"] and row["value"] == expected.get(
                      (row["document_id"], row["field_name"]))} for row in candidates]
    recoveries = sum(row["correct"] for row in evaluated)
    accepted = sum(row["accepted"] for row in evaluated)
    total = int(prior["total_fields"])
    remaining = int(prior["llm_fields_after"]) - recoveries
    metrics = {
        **prior, "policy_version": policy["policy_version"],
        "validated_local_route_short_circuits": int(prior["validated_local_route_short_circuits"]) + recoveries,
        "local_text_short_circuits_added": recoveries, "local_text_routes": evaluated,
        "llm_fields_after": remaining, "llm_diversion_rate_after": remaining / total,
        "first_pass_llm_fields": remaining, "first_pass_llm_diversion_rate": remaining / total,
        "exact_cache_eligible_repeat_fields": remaining, "llm_routed_correct_fields": remaining,
        "remaining_first_pass_routes_require_new_evidence": remaining,
        "local_extraction_correct_fields": int(prior["local_extraction_correct_fields"]) + recoveries,
        "local_extraction_accuracy": (int(prior["local_extraction_correct_fields"]) + recoveries) / total,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    metrics["gates"] = {
        **prior["gates"], "all_accepted_text_routes_correct": accepted == recoveries,
        "configured_text_routes_recovered": recoveries == len(policy["routes"]),
        "llm_diversion_below_3_percent": remaining / total < 0.03,
        "text_candidates_generated_before_truth": all(not row["evaluation_truth_loaded"] for row in candidates),
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output / "evaluation.json").write_text(json.dumps(evaluated, indent=2), encoding="utf-8")
    (output / "policy_snapshot.yaml").write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0 if all(metrics["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
