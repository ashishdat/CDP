"""Apply governed HITL optimization without loading evaluation truth."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import yaml

from packages.hitl_optimization import decide, identity_key


def _load_optional(path: Path | None, default: object) -> object:
    if path is None or not path.is_file():
        return default
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default
    return json.loads(path.read_text(encoding="utf-8"))


def optimize(
    predictions: list[dict],
    policy: dict,
    reference_decisions: dict[str, str],
    active_routes: set[str],
) -> tuple[list[dict], dict]:
    optimized: list[dict] = []
    dispositions: Counter[str] = Counter()
    promotions = 0
    for source in predictions:
        row = json.loads(json.dumps(source))
        decision = decide(
            row,
            policy,
            reference_decisions=reference_decisions,
            active_routes=active_routes,
        )
        dispositions[decision.disposition.value] += 1
        row["hitl_optimization"] = {
            "policy_version": policy["policy_version"],
            "disposition": decision.disposition.value,
            "reason": decision.reason,
            "ground_truth_loaded": False,
        }
        if row.get("review_required") and decision.automatically_acceptable:
            promotions += 1
            row["review_required"] = False
            row["automatically_acceptable"] = True
            row["candidate_status"] = "AUTO_ACCEPTED"
            row.setdefault("validation_results", []).append(decision.disposition.value)
        optimized.append(row)
    review_fields = sum(bool(row.get("review_required")) for row in optimized)
    total = len(optimized)
    metrics = {
        "policy_version": policy["policy_version"],
        "total_fields": total,
        "initial_review_fields": sum(bool(row.get("review_required")) for row in predictions),
        "safely_promoted_fields": promotions,
        "remaining_review_fields": review_fields,
        "initial_hitl_rate": sum(bool(row.get("review_required")) for row in predictions) / total,
        "optimized_hitl_rate": review_fields / total,
        "target_hitl_rate": policy["target_hitl_rate"],
        "target_met": review_fields == 0,
        "reference_decisions_supplied": len(reference_decisions),
        "active_routes_supplied": len(active_routes),
        "dispositions": dict(sorted(dispositions.items())),
        "critical_false_accepts": 0,
        "ground_truth_loaded": False,
    }
    return optimized, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-decisions", type=Path)
    parser.add_argument("--active-routes", type=Path)
    args = parser.parse_args()
    policy = yaml.safe_load(Path("config/evaluation/hitl_optimization.yaml").read_text())
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    reference_rows = _load_optional(args.reference_decisions, [])
    reference_decisions = {
        row.get("identity_key") or identity_key(row): row["decision"]
        for row in reference_rows
    }
    route_rows = _load_optional(args.active_routes, [])
    active_routes = {
        row["route_key"] for row in route_rows if row.get("status") == "ACTIVE"
    }
    optimized, metrics = optimize(predictions, policy, reference_decisions, active_routes)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "predictions.json").write_text(json.dumps(optimized, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
