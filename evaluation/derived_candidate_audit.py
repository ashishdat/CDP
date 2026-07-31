"""Export review-only derived evidence without evaluation truth."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    predictions = json.loads(
        Path("evaluation_data/predictions_fixed_family.json").read_text(encoding="utf-8")
    )
    rows = []
    for document in predictions["documents"]:
        for field in document["fields"]:
            evidence = field.get("metadata", {}).get("derived_evidence")
            if evidence:
                rows.append({
                    "document_id": document["document_id"],
                    "field_name": field["field_name"],
                    **evidence,
                    "runtime_disposition": "HUMAN_REVIEW_REQUIRED",
                })
    output = Path("evaluation_results/derived_candidates.json")
    output.write_text(json.dumps({
        "policy_version": "extraction-v2",
        "derived_candidates": rows,
    }, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} review-only derived candidates to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
