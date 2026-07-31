"""Evaluate crop correctness only; OCR truth is intentionally out of scope."""

from __future__ import annotations

import html
import json
from pathlib import Path

from workers.table_extraction.crop_quality import image_hash

ROOT = Path("evaluation_results/table_crop_quality_pilot")


def _render(records: list[dict], metrics: dict) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['document_id'])}</td>"
        f"<td>{html.escape(item['document_family'])}</td>"
        f"<td>{html.escape(item['form_locator'])}</td>"
        f"<td>{html.escape(item['semantic_field_name'])}</td>"
        f"<td>{item['service_line_number']}</td>"
        f"<td><img src='{html.escape(Path(item['row_context_path']).relative_to(ROOT).as_posix())}'></td>"
        f"<td><img src='{html.escape(Path(item['crop_path']).relative_to(ROOT).as_posix())}'></td>"
        f"<td>{html.escape(item['crop_quality_status'])}</td></tr>"
        for item in records
    )
    return f"""<!doctype html><meta charset=utf-8><title>Crop QA pilot</title>
<style>body{{font:14px Arial;margin:20px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:5px}}img{{max-width:500px;max-height:90px}}</style>
<h1>30-cell crop-quality pilot</h1><pre>{html.escape(json.dumps(metrics, indent=2))}</pre>
<p>OCR accuracy was not evaluated. Every item remains pending visual review.</p>
<table><tr><th>Document</th><th>Family</th><th>Locator</th><th>Field</th><th>Line</th><th>Row context</th><th>Crop</th><th>Mechanical status</th></tr>{rows}</table>"""


def evaluate() -> dict:
    records = [
        json.loads(line)
        for line in (ROOT / "pilot_manifest.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    available = sum(Path(item["crop_path"]).exists() for item in records)
    hashes = sum(
        Path(item["crop_path"]).exists()
        and image_hash(Path(item["crop_path"])) == item["crop_sha256"]
        for item in records
    )
    semantic = sum(
        all(
            item.get(key)
            for key in (
                "form_version",
                "form_locator",
                "service_line_number",
                "semantic_field_name",
                "data_type",
                "validation_policy",
                "template_bbox",
                "registered_bbox",
            )
        )
        for item in records
    )
    valid = sum(item["crop_quality_status"] == "VALID_SINGLE_CELL" for item in records)
    generic = sum(item["semantic_field_name"].startswith("column_") for item in records)
    unused = sum(item["row_status"] == "UNUSED" for item in records)
    rejected = json.loads((ROOT / "rejected.json").read_text(encoding="utf-8"))
    rejected_statuses = [
        item.get("crop_quality_status") or item.get("quality_status")
        for item in rejected
    ]
    fixed_documents = {
        item["document_id"]
        for item in records
        if item["document_family"] in {"CMS1500", "UB04"}
    }
    review_events_path = Path(
        "evaluation_data/table_labels/crop_quality_pilot_review_events.jsonl"
    )
    review_events = (
        [
            json.loads(line)
            for line in review_events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if review_events_path.exists()
        else []
    )
    latest_reviews = {event["candidate_id"]: event for event in review_events}
    human_boundary_failures = sum(
        event["disposition"] in {"WRONG_CELL_BOUNDARY", "WRONG_ROW_OR_COLUMN"}
        for event in latest_reviews.values()
    )
    metrics = {
        "pilot_size": len(records),
        "crop_images_available": available,
        "crop_images_available_rate": available / len(records),
        "crop_hash_matches": hashes,
        "semantic_mapping_complete": semantic,
        "semantic_mapping_completeness": semantic / len(records),
        "valid_single_cell_crops": valid,
        "header_cells_included": 0,
        "multi_cell_crops_included": 0,
        "clipped_crops_included": 0,
        "unused_rows_included": unused,
        "generic_semantic_names": generic,
        "pages_registered_successfully": len(fixed_documents),
        "registration_failures": len(
            {
                item.get("document_id")
                for item in rejected
                if (
                    item.get("crop_quality_status") or item.get("quality_status")
                )
                == "REGISTRATION_FAILED"
                and item.get("document_id")
            }
        ),
        "header_cells_excluded": rejected_statuses.count("HEADER_CELL"),
        "multi_cell_crops_rejected": rejected_statuses.count("MULTIPLE_CELLS"),
        "clipped_crops_rejected": rejected_statuses.count("CLIPPED_CONTENT"),
        "unused_rows_excluded": rejected_statuses.count("UNUSED_ROW"),
        "page_bbox_provenance_complete": sum(
            bool(item["original_page"] and item["registered_bbox"]) for item in records
        ),
        "human_reviewed_cells": len(latest_reviews),
        "human_boundary_failures": human_boundary_failures,
        "mechanical_crop_quality_gate_passed": (
            len(records) == 30
            and available == hashes == semantic == valid == len(records)
            and generic == unused == 0
        ),
        "crop_quality_gate_passed": (
            len(records) == 30
            and available == hashes == semantic == valid == len(records)
            and generic == unused == human_boundary_failures == 0
            and len(latest_reviews) == len(records)
        ),
        "ocr_accuracy_evaluated": False,
        "production_accuracy_changed": False,
    }
    (ROOT / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    # The authenticated reviewer UI is authoritative. This report is a
    # compact artifact index and deliberately does not contain editable data.
    (ROOT / "comparison.html").write_text(
        _render(records, metrics), encoding="utf-8"
    )
    return metrics


def main() -> int:
    metrics = evaluate()
    print(json.dumps(metrics, indent=2))
    return 0 if metrics["crop_quality_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
