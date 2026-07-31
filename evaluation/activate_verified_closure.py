"""Create real open review tasks; never fabricates corrections or approvals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIELDS = {
    "A-06": ("patient_first", "patient_last"),
    "D-01": ("patient_first", "patient_last"),
}


def main() -> int:
    evidence = json.loads(
        Path("evaluation_results/targeted_handwriting_review/results.json").read_text()
    )
    tasks = []
    for document_id, fields in FIELDS.items():
        records = [row for row in evidence if row["document_id"] == document_id]
        crops = [row["crop_path"] for row in records]
        candidates = sorted({
            row.get("ocr", {}).get("text", "") for row in records
            if row.get("ocr", {}).get("text")
        })
        for field in fields:
            task_id = hashlib.sha256(f"{document_id}|{field}|verified-closure-v1".encode()).hexdigest()
            tasks.append({
                "task_id": task_id, "document_id": document_id, "field_name": field,
                "document_family": "CMS1500" if document_id.startswith("A-") else "psychological_receipt",
                "status": "OPEN", "outcome": "INSUFFICIENT_EVIDENCE",
                "primary_crop": crops[0], "crop_variants": crops,
                "ocr_candidates": candidates, "reviewer_correction": None,
                "second_approval_required": True, "finalization_allowed": False,
                "training_export_status": "AWAITING_APPROVED_CORRECTION",
            })
    output = Path("evaluation_results/verified_closure")
    output.mkdir(parents=True, exist_ok=True)
    (output / "tasks.json").write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    metrics = {
        "automated_extraction_accuracy": json.loads(
            Path("evaluation_results/current_v2_router/metrics.json").read_text()
        )["extraction_accuracy"],
        "human_reviewed_field_count": 0,
        "human_verified_final_accuracy": None,
        "critical_unresolved_field_count": len(tasks),
        "review_tasks_open": len(tasks),
        "audit_completeness": 1.0,
        "review_turnaround_seconds": None,
        "corrected_field_audit_events": 0,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
