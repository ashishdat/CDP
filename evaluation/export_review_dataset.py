"""Export unresolved crop references for review, bake-off, and active learning."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evaluation.schemas import PredictionDataset


def _split(document_id: str) -> str:
    # Group exclusively by document. Writer ID can replace document_id when an
    # approved de-identified writer key becomes available.
    bucket = int(hashlib.sha256(document_id.encode()).hexdigest()[:8], 16) % 100
    return "training" if bucket < 70 else ("validation" if bucket < 85 else "holdout")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path,
        default=Path("evaluation_results/review_queue/manifest.jsonl"),
    )
    parser.add_argument("--dataset-version", default="review-crops-v1")
    args = parser.parse_args()
    predictions = PredictionDataset.model_validate_json(
        args.predictions.read_text(encoding="utf-8")
    )
    rows = []
    for document in predictions.documents:
        for field in document.fields:
            metadata = field.metadata
            if metadata.get("disposition") != "HUMAN_REVIEW_REQUIRED":
                continue
            candidates = metadata.get("ocr_candidates", [])
            engines = sorted({str(item.get("engine")) for item in candidates})
            disagreement = len({str(item.get("value")) for item in candidates if item.get("value")}) > 1
            critical = "critical_field" in str(metadata.get("disposition_reason", "")) or (
                "person_name_requires" in str(metadata.get("disposition_reason", ""))
            )
            priority = 100 * int(critical) + 20 * int(disagreement) + max(
                0, int((1 - (field.confidence or 0)) * 10)
            )
            rows.append({
                "dataset_version": args.dataset_version,
                "document_id": document.document_id,
                "field_name": field.field_name,
                "crop_reference": field.crop_reference,
                "current_value": field.raw_value,
                "engines": engines,
                "candidate_count": len(candidates),
                "critical": critical,
                "model_disagreement": disagreement,
                "priority": priority,
                "split": _split(document.document_id),
                "status": "AWAITING_REVIEW",
            })
    rows.sort(key=lambda row: (-row["priority"], row["document_id"], row["field_name"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    summary = {
        "dataset_version": args.dataset_version,
        "count": len(rows),
        "critical": sum(row["critical"] for row in rows),
        "training": sum(row["split"] == "training" for row in rows),
        "validation": sum(row["split"] == "validation" for row in rows),
        "holdout": sum(row["split"] == "holdout" for row in rows),
    }
    args.output.with_name("summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
