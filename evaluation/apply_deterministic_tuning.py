"""Replay conservative deterministic tuning without claiming holdout certification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.deterministic_field_tuning import eligible_for_consensus_acceptance


def tune(rows: list[dict]) -> tuple[list[dict], dict]:
    promoted = 0
    for row in rows:
        if not row.get("review_required"):
            continue
        result = eligible_for_consensus_acceptance(row)
        row.setdefault("deterministic_tuning", {})
        row["deterministic_tuning"].update({
            "normalized_value": result.normalized_value,
            "eligible": result.valid,
            "evidence": result.evidence,
            "scope": "CURRENT_SAMPLE_REPLAY_HOLDOUT_PENDING",
        })
        if result.valid:
            row["normalized_value"] = result.normalized_value
            row["review_required"] = False
            row["automatically_acceptable"] = True
            row["candidate_status"] = "AUTO_ACCEPTED_CURRENT_SAMPLE_REPLAY"
            row.setdefault("validation_results", []).extend([
                result.evidence, "DETERMINISTIC_CROSS_ENGINE_CONSENSUS",
            ])
            promoted += 1
    remaining = sum(bool(row.get("review_required")) for row in rows)
    return rows, {
        "total_fields": len(rows),
        "input_review_fields": promoted + remaining,
        "deterministically_promoted_fields": promoted,
        "remaining_review_fields": remaining,
        "scope": "CURRENT_SAMPLE_REPLAY_HOLDOUT_PENDING",
        "production_generalization_claim": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.predictions.read_text(encoding="utf-8"))
    tuned, metrics = tune(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "predictions.json").write_text(json.dumps(tuned, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
