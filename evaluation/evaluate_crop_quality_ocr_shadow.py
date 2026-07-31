"""Evaluate persisted pilot OCR only against independently reviewed values."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from workers.table_extraction.field_candidate_parsing import parsed_alternatives

PILOT = Path("evaluation_results/table_crop_quality_pilot")
REVIEWS = Path("evaluation_data/table_labels/crop_quality_pilot_review_events.jsonl")


def _normalize(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def main() -> int:
    candidates = json.loads((PILOT / "ocr_shadow/candidates.json").read_text(encoding="utf-8"))
    ppocr_path = PILOT / "ocr_shadow/ppocr_candidates.json"
    if ppocr_path.is_file():
        candidates.extend(json.loads(ppocr_path.read_text(encoding="utf-8")))
    manifest = {
        row["candidate_id"]: row
        for row in (
            json.loads(line)
            for line in (PILOT / "pilot_manifest.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    reviews = [
        json.loads(line) for line in REVIEWS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nonblank_counts = Counter(
        (
            manifest[row["candidate_id"]]["document_id"],
            _normalize(row.get("expected_value")),
        )
        for row in reviews
        if _normalize(row.get("expected_value"))
    )
    invalid_review_ids = {
        row["candidate_id"]
        for row in reviews
        if nonblank_counts[
            (
                manifest[row["candidate_id"]]["document_id"],
                _normalize(row.get("expected_value")),
            )
        ] >= 3
    }
    truth = {
        row["candidate_id"]: row.get("expected_value", "")
        for row in reviews
        if row["candidate_id"] not in invalid_review_ids
    }
    evaluated = {}
    for candidate_id, expected in truth.items():
        options = [row for row in candidates if row["candidate_id"] == candidate_id]
        correct = [row for row in options if _normalize(row["raw_value"]) == _normalize(expected)]
        parsed = []
        for option in options:
            for alternative in parsed_alternatives(
                option["raw_value"], manifest[candidate_id]["data_type"]
            ):
                parsed.append({**alternative, "parent_candidate": option})
        correct_parsed = [
            row for row in parsed if _normalize(row["value"]) == _normalize(expected)
        ]
        evaluated[candidate_id] = {
            "expected": expected,
            "correct_candidate_present": bool(correct),
            "correct_parsed_alternative_present": bool(correct_parsed),
            "correct_candidates": correct,
            "correct_parsed_alternatives": correct_parsed,
            "all_candidates": options,
        }
    correct = sum(row["correct_candidate_present"] for row in evaluated.values())
    parsed_correct = sum(
        row["correct_candidate_present"] or row["correct_parsed_alternative_present"]
        for row in evaluated.values()
    )
    tesseract_correct = sum(
        any(
            row["independence_group"] == "TESSERACT_FAMILY"
            and _normalize(row["raw_value"]) == _normalize(data["expected"])
            for row in data["all_candidates"]
        )
        for data in evaluated.values()
    )
    paddle_correct = sum(
        any(
            row["independence_group"] == "PADDLE_FAMILY"
            and _normalize(row["raw_value"]) == _normalize(data["expected"])
            for row in data["all_candidates"]
        )
        for data in evaluated.values()
    )
    report = {
        "manifest_fields": len({row["candidate_id"] for row in candidates}),
        "reviewed_fields_evaluated": len(evaluated),
        "unreviewed_fields_not_scored": 30 - len(reviews),
        "semantically_invalid_review_labels": len(invalid_review_ids),
        "semantically_valid_review_labels": len(evaluated),
        "correct_candidate_coverage_on_reviewed_fields": (
            correct / len(evaluated) if evaluated else None
        ),
        "correct_reviewed_fields": correct,
        "raw_candidate_coverage_by_family": {
            "TESSERACT_FAMILY": tesseract_correct / len(evaluated) if evaluated else None,
            "PADDLE_FAMILY": paddle_correct / len(evaluated) if evaluated else None,
        },
        "review_only_parsed_alternative_ceiling": (
            parsed_correct / len(evaluated) if evaluated else None
        ),
        "review_only_parsed_correct_fields": parsed_correct,
        "production_accuracy_changed": False,
        "candidate_authority": "REVIEW_ONLY",
        "denominator_note": "Accuracy uses only submitted reviewer values; unreviewed crops are not assumed correct.",
    }
    output = PILOT / "ocr_shadow"
    (output / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "evaluation_details.json").write_text(
        json.dumps(evaluated, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
