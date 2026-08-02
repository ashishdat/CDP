"""Rank review pages so tuning work reduces per-page HITL cost first."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def prioritize(rows: list[dict]) -> list[dict]:
    pages: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        if not row.get("review_required"):
            continue
        identity = row.get("field_identity") or {}
        pages[(str(identity.get("document_id")), int(identity.get("page_number") or 0))].append(row)
    ranked = []
    for (document_id, page_number), fields in pages.items():
        ranked.append({
            "document_id": document_id,
            "page_number": page_number,
            "review_field_count": len(fields),
            "field_names": [(row.get("field_identity") or {}).get("semantic_field") for row in fields],
            "potential_page_savings_usd": 1.0,
            "status": "REFERENCE_OR_INDEPENDENT_CONSENSUS_REQUIRED",
        })
    return sorted(ranked, key=lambda row: (row["review_field_count"], row["document_id"], row["page_number"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.predictions.read_text(encoding="utf-8"))
    result = prioritize(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"review_pages": len(result), "ranked_pages": len(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
