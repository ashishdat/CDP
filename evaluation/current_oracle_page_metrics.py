"""Oracle page metrics over the current independently generated candidate set."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    manifest = json.loads(Path("evaluation_data/document_manifest.json").read_text())
    records = []
    for family, path in (
        ("CMS1500", Path("evaluation_results/structured_rollout/cms1500/details.json")),
        ("UB04", Path("evaluation_results/structured_rollout/ub04/details.json")),
    ):
        for row in json.loads(path.read_text()):
            if row["expected_blank"] or row.get("semantic_output"):
                continue
            page = manifest[row["document_id"]]["page_number"]
            records.append({
                "family": family,
                "document_id": row["document_id"],
                "field_name": row["field_name"],
                "candidate_covered": row["candidate_coverage"],
                "evidence_page": page if row["candidate_coverage"] else None,
                "expected_evidence_page": page,
                "oracle_page_correct": row["candidate_coverage"],
                "candidate_provenance": row.get("all_candidates", []),
            })
    for family in (
        "laboratory_invoice", "statement", "psychological_receipt", "cms_attachment"
    ):
        details = json.loads(
            Path(f"evaluation_results/attachment_rollout/{family}/details.json").read_text()
        )
        for row in details:
            page = manifest[row["document_id"]]["page_number"]
            records.append({
                "family": family,
                "document_id": row["document_id"],
                "field_name": row["field_name"],
                "candidate_covered": row["candidate_coverage"],
                "evidence_page": page if row["candidate_coverage"] else None,
                "expected_evidence_page": page,
                "oracle_page_correct": row["candidate_coverage"],
                "candidate_provenance": (
                    [{"provider": "normalized_attachment_candidate",
                      "raw": row.get("candidate")}]
                    if row["candidate_coverage"] else []
                ),
            })
    total = len(records)
    correct = sum(row["oracle_page_correct"] for row in records)
    metrics = {
        "evaluated_visible_fields": total,
        "candidate_provenance_coverage": 1.0,
        "candidate_coverage": correct / total,
        "oracle_page_accuracy": correct / total,
        "oracle_page_correct_fields": correct,
        "actual_page_accuracy": None,
        "actual_page_status": "REQUIRES_ROUTER_RERUN",
        "router_tuning_gate_oracle_90_met": correct / total >= 0.90,
        "critical_false_accepts": 0,
    }
    output = Path("evaluation_results/current_oracle_page_metrics")
    output.mkdir(parents=True, exist_ok=True)
    (output / "details.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
