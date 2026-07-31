"""Governed metrics for crop-pilot reviews, separate from OCR accuracy."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

import yaml

PILOT = Path("evaluation_results/table_crop_quality_pilot")
EVENTS = Path(
    "evaluation_data/table_labels/crop_quality_pilot_review_events.jsonl"
)


def _normalize(value: str) -> str:
    return " ".join(value.upper().split())


def evaluate() -> tuple[dict, list[dict]]:
    manifest = [
        json.loads(line)
        for line in (PILOT / "pilot_manifest.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    indexed = {item["candidate_id"]: item for item in manifest}
    events = (
        [
            json.loads(line)
            for line in EVENTS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if EVENTS.exists()
        else []
    )
    grouped: dict[str, list[dict]] = {}
    for event in events:
        if event["candidate_id"] in indexed:
            grouped.setdefault(event["candidate_id"], []).append(event)
    latest = {candidate_id: items[-1] for candidate_id, items in grouped.items()}
    details = []
    ocr_attempted = ocr_correct = 0
    boundary_failures = 0
    for candidate_id, event in latest.items():
        candidate = indexed[candidate_id]
        suggestion = candidate.get("ocr_suggestion", "")
        if suggestion:
            ocr_attempted += 1
            ocr_correct += _normalize(suggestion) == _normalize(
                event["expected_value"]
            )
        boundary_failures += event["disposition"] in {
            "WRONG_CELL_BOUNDARY",
            "WRONG_ROW_OR_COLUMN",
        }
        details.append(
            {
                **candidate,
                "review": event,
                "ocr_suggestion_matches_review": (
                    _normalize(suggestion) == _normalize(event["expected_value"])
                    if suggestion
                    else None
                ),
            }
        )
    baseline = yaml.safe_load(
        Path("config/releases/extraction-v2.yaml").read_text(encoding="utf-8")
    )["baseline_metrics"]
    final_approved = sum(
        event["status"] == "APPROVED" for event in latest.values()
    )
    pending_second = sum(
        event["status"] == "AWAITING_SECOND_APPROVAL"
        for event in latest.values()
    )
    metrics = {
        "pilot_manifest_cells": len(manifest),
        "raw_review_events": len(events),
        "unique_cells_reviewed": len(latest),
        "duplicate_primary_events_preserved": len(events) - len(latest),
        "review_completion_rate": len(latest) / len(manifest),
        "final_approved_cells": final_approved,
        "awaiting_independent_second_approval": pending_second,
        "unreviewed_cells": len(manifest) - len(latest),
        "visually_verified_cells": sum(
            bool(event.get("visual_verified")) for event in latest.values()
        ),
        "reviewed_boundary_failures": boundary_failures,
        "reviewed_crop_acceptance_rate": (
            (len(latest) - boundary_failures) / len(latest) if latest else None
        ),
        "dispositions": dict(
            Counter(event["disposition"] for event in latest.values())
        ),
        "ocr_suggestion_fields_attempted": ocr_attempted,
        "ocr_suggestion_correct": ocr_correct,
        "ocr_suggestion_normalized_accuracy": (
            ocr_correct / ocr_attempted if ocr_attempted else None
        ),
        "ocr_accuracy_status": (
            "EVALUATED" if ocr_attempted else "UNAVAILABLE_NO_OCR_EVIDENCE"
        ),
        "production_automated_accuracy": baseline["automated_accuracy"],
        "production_accuracy_changed": False,
        "critical_false_accepts": baseline["critical_false_accepts"],
        "pilot_labels_evaluation_eligible": False,
        "pilot_labels_training_eligible": False,
    }
    return metrics, details


def render(metrics: dict, details: list[dict]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['document_id'])}</td>"
        f"<td>{html.escape(item['semantic_field_name'])}</td>"
        f"<td>{html.escape(item['form_locator'])}</td>"
        f"<td>{html.escape(item.get('ocr_suggestion') or '(not attempted)')}</td>"
        f"<td>{html.escape(item['review']['expected_value'] or '(blank confirmed)')}</td>"
        f"<td>{html.escape(item['review']['disposition'])}</td>"
        f"<td>{html.escape(item['review']['status'])}</td></tr>"
        for item in details
    )
    return f"""<!doctype html><meta charset=utf-8><title>Pilot review metrics</title>
<style>body{{font:14px Arial;margin:24px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:6px}}th{{background:#eef}}</style>
<h1>Crop-quality pilot review metrics</h1><pre>{html.escape(json.dumps(metrics, indent=2))}</pre>
<p>Production accuracy is frozen. Pilot crop reviews are not an OCR-accuracy dataset.</p>
<table><tr><th>Document</th><th>Field</th><th>Locator</th><th>Unverified OCR</th><th>Reviewed value</th><th>Disposition</th><th>Status</th></tr>{rows}</table>"""


def publish() -> dict:
    metrics, details = evaluate()
    (PILOT / "review_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    (PILOT / "review_comparison.html").write_text(
        render(metrics, details), encoding="utf-8"
    )
    return metrics


def main() -> int:
    metrics = publish()
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
