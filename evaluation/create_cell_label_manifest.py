"""Create a truth-free, stratified queue from persisted table candidates."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    source = Path("evaluation_results/table_shadow_v2/candidates.jsonl")
    output = Path("evaluation_data/table_labels/cell_label_manifest.jsonl")
    candidates = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Deterministic round-robin by family; blanks are retained.
    groups: dict[str, list[dict]] = {}
    for candidate in candidates:
        groups.setdefault(candidate["document_family"], []).append(candidate)
    selected: list[dict] = []
    while len(selected) < min(150, len(candidates)) and any(groups.values()):
        for family in sorted(groups):
            if groups[family] and len(selected) < 150:
                selected.append(groups[family].pop(0))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for candidate in selected:
            item = {
                key: candidate[key] for key in (
                    "candidate_id", "document_id", "page_number",
                    "document_family", "table_type", "table_index",
                    "row_index", "column_name", "cell_bbox", "image_sha256",
                )
            }
            item.update({
                "raw_text_for_reviewer": candidate["raw_text"],
                "writing_type": "UNCLASSIFIED",
                "content_category": "BLANK" if not candidate["raw_text"].strip() else "UNCLASSIFIED",
                "label_status": "AWAITING_HUMAN_LABEL",
                "assigned_primary_reviewer": (
                    f"primary-reviewer-{(len(selected) % 3) + 1}"
                ),
                "priority": (
                    1 if candidate["document_family"] in {
                        "UB04", "laboratory_invoice", "statement"
                    } else 2
                ),
            })
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    print(json.dumps({"manifest_items": len(selected), "approved_labels_fabricated": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
