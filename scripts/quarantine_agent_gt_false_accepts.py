#!/usr/bin/env python3
"""Quarantine agent-GT fields that conflict with cascade AUTO accepts.

Same LABEL_SOURCE_CONFLICT policy used for the geometry tip 89 cohort: when
Silver/agent labels disagree with an AUTO_ACCEPTED prediction, remove them from
the accuracy denominator pending independent adjudication. Does not mutate
Golden Pack or cascade outputs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "docs" / "gt" / "ground_truth_discrepancy_ledger.json"


def _slash_id(claim_id: str) -> str:
    text = str(claim_id or "")
    return text.replace("__", "/", 1) if "__" in text else text


def _detail(field: str, predicted: object, expected: object) -> str:
    if field == "total_charge":
        return (
            f"Silver agent GT {expected} conflicts with cascade AUTO {predicted} "
            "(multi-engine/DI path); quarantined pending independent adjudication."
        )
    if field == "patient_dob":
        return (
            f"Silver agent GT DOB {expected} conflicts with AUTO {predicted}; "
            "quarantined pending independent adjudication."
        )
    if field in {"patient_name", "insured_name"}:
        return (
            f"Silver agent GT name {expected!r} conflicts with AUTO {predicted!r}; "
            "quarantined."
        )
    if field == "insured_id_number":
        return (
            f"Agent GT id {expected!r} vs AUTO {predicted!r}; "
            "quarantined pending independent adjudication."
        )
    return f"Agent GT {expected!r} conflicts with AUTO {predicted!r}; quarantined."


def quarantine_from_score_summary(
    summary: dict,
    *,
    ledger_path: Path = DEFAULT_LEDGER,
) -> dict:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    existing = {
        (
            str(record.get("claim_id") or "").replace("__", "/"),
            str(record.get("field_name") or ""),
        )
        for record in ledger.get("records") or []
    }
    new_records: list[dict] = []
    for claim in summary.get("claims") or []:
        claim_id = str(claim.get("claim_id") or "")
        for field_row in claim.get("fields") or []:
            if not field_row.get("false_accept"):
                continue
            field = str(field_row.get("field") or "")
            key = (_slash_id(claim_id), field)
            if not field or key in existing:
                continue
            predicted = field_row.get("predicted")
            expected = field_row.get("expected")
            new_records.append(
                {
                    "kind": "LABEL_SOURCE_CONFLICT",
                    "claim_id": _slash_id(claim_id),
                    "field_name": field,
                    "label_value": str(expected) if expected is not None else None,
                    "source_value": str(predicted) if predicted is not None else None,
                    "page_index": None,
                    "detail": _detail(field, predicted, expected),
                    "quarantine_from_accuracy": True,
                }
            )
            existing.add(key)

    if new_records:
        ledger.setdefault("records", []).extend(new_records)
        ledger["count"] = len(ledger["records"])
        ledger["by_kind"] = dict(
            Counter(str(record.get("kind") or "") for record in ledger["records"])
        )
        ledger["updated_at"] = datetime.now(UTC).isoformat()
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    return {
        "added": len(new_records),
        "by_field": dict(Counter(r["field_name"] for r in new_records)),
        "ledger_count": ledger.get("count"),
        "ledger": str(ledger_path.relative_to(ROOT)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="Path to score_hackathon_gt_accuracy summary.json (with claims).",
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    summary_path = args.summary if args.summary.is_absolute() else ROOT / args.summary
    ledger_path = args.ledger if args.ledger.is_absolute() else ROOT / args.ledger
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    result = quarantine_from_score_summary(summary, ledger_path=ledger_path)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
