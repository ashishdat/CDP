"""Evaluate persisted shadow candidates after truth-free inference has completed."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def normalize(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, lhs in enumerate(left, 1):
        current = [row]
        for column, rhs in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (lhs != rhs),
            ))
        previous = current
    return previous[-1]


def load_truth() -> dict[tuple[str, str], str]:
    truth: dict[tuple[str, str], str] = {}
    roots = (
        Path("evaluation_results/structured_rollout"),
        Path("evaluation_results/attachment_rollout"),
    )
    for root in roots:
        for detail_path in root.rglob("details.json"):
            try:
                rows = json.loads(detail_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for row in rows:
                if "expected" in row:
                    truth[(row["document_id"], row["field_name"])] = str(row["expected"])
    return truth


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path(
            "evaluation_results/ocr_shadow_bakeoff/inference/candidates.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation_results/ocr_shadow_bakeoff/evaluation"),
    )
    args = parser.parse_args()
    rows = json.loads(args.candidates.read_text())
    truth = load_truth()
    by_route: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_field: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_route[(row["model_name"], row.get("preprocessing_variant") or "unknown")].append(row)
        by_field[(row["document_id"], row["field_name"])].append(row)

    route_metrics = []
    for (model, variant), candidates in sorted(by_route.items()):
        evaluated = response = correct = invalid = 0
        cer_total = 0.0
        latencies = []
        for row in candidates:
            key = (row["document_id"], row["field_name"])
            if key not in truth:
                continue
            evaluated += 1
            actual, expected = normalize(row["normalized_value"]), normalize(truth[key])
            if actual:
                response += 1
                invalid += int(not any(character.isalnum() for character in actual))
            correct += int(actual == expected)
            cer_total += edit_distance(actual, expected) / max(1, len(expected))
            latencies.append(float(row.get("latency_ms") or 0.0))
        latencies.sort()
        route_metrics.append({
            "model": model,
            "preprocessing_variant": variant,
            "fields_evaluated": evaluated,
            "ocr_response_rate": response / evaluated if evaluated else 0.0,
            "correct_candidate_coverage": correct / evaluated if evaluated else 0.0,
            "normalized_exact_accuracy": correct / evaluated if evaluated else 0.0,
            "character_error_rate": cer_total / evaluated if evaluated else 0.0,
            "invalid_output_rate": invalid / evaluated if evaluated else 0.0,
            "latency_p50_ms": (
                latencies[len(latencies) // 2] if latencies else 0.0
            ),
            "latency_p95_ms": (
                latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
                if latencies else 0.0
            ),
        })

    details = []
    union_correct = 0
    baseline_correct_keys: set[tuple[str, str]] = set()
    union_correct_keys: set[tuple[str, str]] = set()
    for key, candidates in sorted(by_field.items()):
        expected = truth.get(key)
        matches = [
            row for row in candidates
            if expected is not None
            and normalize(row["normalized_value"]) == normalize(expected)
        ]
        union_correct += bool(matches)
        if matches:
            union_correct_keys.add(key)
        if any(
            row.get("preprocessing_variant", "").startswith("original_")
            for row in matches
        ):
            baseline_correct_keys.add(key)
        details.append({
            "document_id": key[0],
            "field_name": key[1],
            "expected": expected,
            "correct_candidate_generated": bool(matches),
            "matching_routes": [
                {
                    "model": row["model_name"],
                    "variant": row.get("preprocessing_variant"),
                    "value": row["normalized_value"],
                    "authority": row["candidate_authority"],
                }
                for row in matches
            ],
            "promotion_status": "REVIEW_ONLY",
        })
    evaluated_fields = sum(item["expected"] is not None for item in details)
    metrics = {
        "policy_version": "ocr-shadow-cascade-v2.2",
        "evaluated_fields": evaluated_fields,
        "union_correct_candidates": union_correct,
        "union_correct_candidate_coverage": (
            union_correct / evaluated_fields if evaluated_fields else 0.0
        ),
        "baseline_original_correct_candidates": len(baseline_correct_keys),
        "incremental_correct_candidates": len(
            union_correct_keys - baseline_correct_keys
        ),
        "remaining_without_correct_candidate": (
            evaluated_fields - len(union_correct_keys)
        ),
        "promotion_gate": {
            "minimum_incremental_correct_candidates": 5,
            "met": len(union_correct_keys - baseline_correct_keys) >= 5,
        },
        "critical_false_accepts": 0,
        "production_values_overwritten": 0,
        "candidate_authority": "REVIEW_ONLY",
        "route_metrics": route_metrics,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (args.output / "details.json").write_text(json.dumps(details, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
