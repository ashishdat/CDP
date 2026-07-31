"""Create a truth-free, stratified queue from persisted table candidates."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path


def select_candidates(candidates: list[dict], limit: int = 150) -> list[dict]:
    """Deterministically balance family, content and column.

    This is truth-free: raw OCR is used only to distinguish observed blank
    from observed nonblank. Cycling through columns prevents a large repeated
    service-line grid from consuming a family's entire allocation.
    """
    strata: dict[tuple[str, str, str], deque[dict]] = defaultdict(deque)
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item["document_family"],
            item["column_name"],
            item["document_id"],
            item["page_number"],
            item["row_index"],
        ),
    ):
        observed = "OBSERVED_NONBLANK" if candidate["raw_text"].strip() else "OBSERVED_BLANK"
        strata[(candidate["document_family"], observed, candidate["column_name"])].append(
            candidate
        )
    selected: list[dict] = []
    target = min(limit, len(candidates))
    for content_class in ("OBSERVED_NONBLANK", "OBSERVED_BLANK"):
        keys = sorted(key for key in strata if key[1] == content_class)
        while len(selected) < target and keys:
            remaining = []
            for key in keys:
                if strata[key] and len(selected) < target:
                    selected.append(strata[key].popleft())
                if strata[key]:
                    remaining.append(key)
            keys = remaining
    return selected


def main() -> int:
    source = Path("evaluation_results/table_shadow_v2/candidates.jsonl")
    output = Path("evaluation_data/table_labels/cell_label_manifest.jsonl")
    candidates = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = select_candidates(candidates)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for index, candidate in enumerate(selected):
            item = {
                key: candidate[key] for key in (
                    "candidate_id", "document_id", "page_number",
                    "document_family", "table_type", "table_index",
                    "row_index", "column_name", "cell_bbox", "image_sha256",
                )
            }
            item.update({
                "raw_text_for_reviewer": candidate["raw_text"],
                "writing_type": "NOT_ASSESSED",
                "content_category": (
                    "OBSERVED_BLANK"
                    if not candidate["raw_text"].strip()
                    else "OBSERVED_NONBLANK"
                ),
                "label_status": "AWAITING_HUMAN_LABEL",
                "assigned_primary_reviewer": (
                    f"primary-reviewer-{(index % 3) + 1}"
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
