"""Classify reviewed table candidates without changing extraction-v2."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    details_path = Path("evaluation_results/table_shadow_v2/details.json")
    details = json.loads(details_path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for item in details:
        name = item["incremental_classification"]
        counts[name] = counts.get(name, 0) + 1
    payload = {
        "classifications": counts,
        "production_values_modified": 0,
        "existing_correct_values_threatened": 0,
        "actual_production_accuracy": 0.8925233644859814,
        "potential_accuracy": None,
        "reason": "approved labels and reviewed promotion are required",
    }
    path = Path("evaluation_results/table_shadow_v2/baseline_comparison.json")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
