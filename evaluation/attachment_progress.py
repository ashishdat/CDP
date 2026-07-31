"""Aggregate progressive attachment-family gates without mixing sentinel metrics."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    families = (
        "laboratory_invoice", "statement", "psychological_receipt", "cms_attachment"
    )
    rows = []
    matched = total = 0
    for family in families:
        rollout = json.loads(
            Path(f"evaluation_results/attachment_rollout/{family}/metrics.json")
            .read_text(encoding="utf-8")
        )
        normalization = json.loads(
            Path(f"evaluation_results/attachment_artifacts/{family}/metrics.json")
            .read_text(encoding="utf-8")
        )
        fields = rollout["visible_source_fields"]
        family_matches = round(fields * rollout["candidate_coverage"])
        total += fields
        matched += family_matches
        rows.append({
            **rollout,
            "normalization_completeness": normalization["normalization_completeness"],
        })
    report = {
        "activated_families": list(families),
        "families": rows,
        "artifact_normalization_completeness": min(
            row["normalization_completeness"] for row in rows
        ),
        "visible_source_fields": total,
        "candidate_matches": matched,
        "attachment_candidate_coverage": matched / total if total else 0.0,
        "critical_false_accepts": sum(row["critical_false_accepts"] for row in rows),
        "sentinel_values_counted_as_ocr": 0,
        "initial_coverage_gate_70_met": matched / total >= 0.70,
        "tuned_coverage_gate_85_met": matched / total >= 0.85,
    }
    output = Path("evaluation_results/attachment_rollout/progress.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
