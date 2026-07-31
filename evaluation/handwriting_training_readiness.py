"""Report training readiness without fabricating or importing evaluation labels."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    path = Path("evaluation_results/verified_closure/approved_labels.jsonl")
    rows = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ] if path.is_file() else []
    unique = {row["crop_sha256"] for row in rows}
    families = {row["document_family"] for row in rows}
    fields: dict[str, int] = {}
    for row in rows:
        fields[row["field_name"]] = fields.get(row["field_name"], 0) + 1
    metrics = {
        "approved_rows": len(rows),
        "unique_approved_crops": len(unique),
        "document_families": len(families),
        "approved_by_field": fields,
        "pilot_gate": {
            "minimum_unique_crops": 100,
            "minimum_families": 3,
            "met": len(unique) >= 100 and len(families) >= 3,
        },
        "fine_tuning_enabled": False,
        "holdout_required": True,
        "evaluation_ground_truth_allowed_as_label": False,
    }
    output = Path("evaluation_results/handwriting_training_readiness.json")
    output.write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
