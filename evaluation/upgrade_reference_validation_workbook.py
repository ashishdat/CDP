"""Preserve entered decisions while adding the required approval columns."""

from __future__ import annotations

from pathlib import Path

from evaluation.import_governed_reference_xlsx import read_sheet
from evaluation.reference_enrichment_workbook import write_enriched_workbook

DECISION_COLUMNS = {
    "reference_value", "decision", "source_tier", "reference_provider",
    "reference_dataset_version", "source_record_id", "source_lineage",
    "matching_attributes", "contradictions", "independent_truth",
    "approval_method", "evaluation_eligible", "decision_reason",
    "approved_by", "approved_at", "second_approved_by", "second_approved_at",
    "label_strength",
}


def main() -> int:
    root = Path("evaluation_results/reference_validation_six")
    source = root / "reference_validation_six_fields.xlsx"
    destination = root / "reference_validation_six_fields_reviewer_ready.xlsx"
    rows = read_sheet(source, "Reference Decisions")
    original = [{key: value for key, value in row.items() if key not in DECISION_COLUMNS}
                for row in rows]
    decisions = []
    for row in rows:
        decisions.append({key: row.get(key, "") for key in DECISION_COLUMNS} | {
            "identity_key": row["identity_key"],
            "approved_by": row.get("approved_by", ""),
            "approved_at": row.get("approved_at", ""),
            "second_approved_by": row.get("second_approved_by", ""),
            "second_approved_at": row.get("second_approved_at", ""),
            "label_strength": row.get("label_strength", ""),
        })
    write_enriched_workbook(destination, original, decisions,
        {"rows_preserved": len(rows), "approval_columns_added": 5}, [])
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
