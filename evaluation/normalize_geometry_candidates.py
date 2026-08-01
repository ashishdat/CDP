"""Project governed checkbox geometry results into the candidate contract."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    source = Path("evaluation_results/final_four_geometry/candidates.json")
    output = Path("evaluation_results/targeted_diagnostics_v1/geometry_candidates.json")
    rows = []
    for row in json.loads(source.read_text(encoding="utf-8")):
        if not row.get("value") or row.get("ambiguous", True):
            continue
        rows.append({"document_id": row["document_id"], "field_name": row["field_name"],
            "raw_value": row["value"], "normalized_value": row["value"],
            "model_name": "pixel_mark_detector", "preprocessing_variant": "aligned_geometry",
            "raw_confidence": row.get("winning_margin", 0.0),
            "candidate_authority": "REVIEW_ONLY", "failure_reason": None,
            "validation_results": ["single_mark", "minimum_margin_passed"],
            "crop_path": row.get("crop_path"), "ground_truth_loaded": False})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps({"geometry_candidates": len(rows), "ground_truth_loaded": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
