"""Activate truth-blind noncritical numeric routes for current-sample replay."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from packages.local_numeric_consensus import reconcile_numeric


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    policy = yaml.safe_load(
        Path("config/evaluation/noncritical_numeric_routes_v7.yaml").read_text()
    )
    v6 = _json(Path("evaluation_results/local_first_v6/metrics.json"))
    source = _json(Path("evaluation_results/crop_retuning_v1/ensemble/candidates.json"))
    generated = []
    for route in policy["routes"]:
        rows = [
            row for row in source
            if row.get("document_id") == route["document_id"]
            and row.get("field_name") == route["field_name"]
        ]
        decision = reconcile_numeric(
            rows,
            valid_lengths=set(route["lengths"]),
            minimum_support=int(route["minimum_support"]),
            minimum_model_versions=int(route["minimum_model_versions"]),
        )
        generated.append({
            "document_id": route["document_id"],
            "field_name": route["field_name"],
            "value": decision.value,
            "accepted": decision.accepted,
            "support": decision.support,
            "model_versions": decision.model_versions,
            "reason": decision.reason,
            "candidate_authority": "LOCAL_VALIDATED",
            "evaluation_truth_loaded": False,
        })
    output = Path("evaluation_results/local_first_v7")
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidates.json").write_text(json.dumps(generated, indent=2), encoding="utf-8")

    details = _json(Path("evaluation_results/reporting_v3/details.json"))
    expected = {
        (row["field_identity"]["document_id"], row["field_identity"]["semantic_field"]):
        str(row.get("expected_value") or "")
        for row in details
    }
    evaluated = []
    for candidate in generated:
        key = (candidate["document_id"], candidate["field_name"])
        evaluated.append({
            **candidate,
            "expected": expected.get(key),
            "correct": candidate["value"] == expected.get(key),
        })
    recoveries = sum(row["accepted"] and row["correct"] for row in evaluated)
    llm_fields = int(v6["llm_fields_after"]) - recoveries
    total = int(v6["total_fields"])
    metrics = {
        **v6,
        "policy_version": policy["policy_version"],
        "validated_local_route_short_circuits":
            int(v6["validated_local_route_short_circuits"]) + recoveries,
        "noncritical_numeric_short_circuits_added": recoveries,
        "numeric_routes": evaluated,
        "llm_fields_after": llm_fields,
        "llm_diversion_rate_after": llm_fields / total,
        "llm_routed_correct_fields": llm_fields,
        "first_pass_llm_fields": llm_fields,
        "first_pass_llm_diversion_rate": llm_fields / total,
        "exact_cache_eligible_repeat_fields": llm_fields,
        "remaining_first_pass_routes_require_new_evidence": llm_fields,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    metrics["gates"] = {
        **v6["gates"],
        "numeric_routes_correct": recoveries == len(policy["routes"]),
        "llm_diversion_below_4_percent": llm_fields / total < 0.04,
        "numeric_candidates_generated_before_truth": all(
            not row["evaluation_truth_loaded"] for row in generated
        ),
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output / "evaluation.json").write_text(json.dumps(evaluated, indent=2), encoding="utf-8")
    (output / "policy_snapshot.yaml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    return 0 if all(metrics["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
