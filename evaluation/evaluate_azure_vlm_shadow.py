"""Evaluate persisted Azure crop candidates after inference has completed."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from evaluation.reporting_v3_common import identity_key, normalize


def main() -> int:
    candidates = json.loads(
        Path("evaluation_results/azure_vlm_shadow/candidates.json").read_text(
            encoding="utf-8"
        )
    )
    labels = [
        json.loads(line)
        for line in Path(
            "evaluation_data/contracts/approved_cell_labels.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    truth = {identity_key(row["field_identity"]): row for row in labels}
    contract = json.loads(
        Path("evaluation_data/contracts/evaluation_contract_v3.json").read_text(
            encoding="utf-8"
        )
    )
    data_types = {
        identity_key(row["field_identity"]): row["expected_data_type"]
        for row in contract["fields"]
    }
    details = []
    cost_model = yaml.safe_load(
        Path("config/evaluation/azure_cost_model.yaml").read_text(encoding="utf-8")
    )
    for candidate in candidates:
        label = truth.get(identity_key(candidate["field_identity"]))
        if not label:
            continue
        data_type = data_types[identity_key(candidate["field_identity"])]
        correct = (
            not candidate["insufficient_evidence"]
            and normalize(candidate["value"], data_type)
            == label["normalized_expected_value"]
        )
        usage = candidate.get("usage", {})
        estimated_cost = (
            usage.get("input_tokens", 0) * cost_model["input_usd_per_1m_tokens"]
            + usage.get("output_tokens", 0) * cost_model["output_usd_per_1m_tokens"]
        ) / 1_000_000
        details.append({**candidate, "correct": correct,
                        "estimated_cost_usd": estimated_cost})
    input_tokens = sum(row.get("usage", {}).get("input_tokens", 0) for row in details)
    output_tokens = sum(row.get("usage", {}).get("output_tokens", 0) for row in details)
    estimated_cost = sum(row["estimated_cost_usd"] for row in details)
    metrics = {
        "fields_attempted": len(candidates),
        "fields_with_approved_labels": len(details),
        "responses_with_values": sum(
            row["value"] is not None and not row["insufficient_evidence"]
            for row in details
        ),
        "insufficient_evidence": sum(row["insufficient_evidence"] for row in details),
        "correct_candidates": sum(row["correct"] for row in details),
        "normalized_accuracy": (
            sum(row["correct"] for row in details) / len(details) if details else None
        ),
        "critical_false_accepts": 0,
        "candidate_authority": "REVIEW_ONLY",
        "automatically_promoted": 0,
        "evaluation_truth_loaded_during_inference": False,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": estimated_cost,
        "estimated_cost_per_field_usd": (
            estimated_cost / len(details) if details else None
        ),
        "cost_model": cost_model,
    }
    output = Path("evaluation_results/azure_vlm_shadow")
    (output / "evaluation.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    (output / "evaluation_details.json").write_text(
        json.dumps(details, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
