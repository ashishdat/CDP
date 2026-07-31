"""Export unresolved shadow crops into a governed active-learning queue."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RESULTS = Path("evaluation_results")


def split_for(document_id: str) -> str:
    bucket = int(hashlib.sha256(document_id.encode()).hexdigest()[:8], 16) % 100
    return "training" if bucket < 70 else ("validation" if bucket < 85 else "holdout")


def main() -> int:
    details = json.loads(
        (RESULTS / "ocr_shadow_bakeoff/evaluation/details.json").read_text()
    )
    artifacts = json.loads(
        (RESULTS / "ocr_shadow_bakeoff/normalized_crops/artifacts.json").read_text()
    )
    candidates = json.loads(
        (RESULTS / "ocr_shadow_bakeoff/inference/candidates.json").read_text()
    )
    artifacts_by_key = {
        (row["document_id"], row["field_name"]): row for row in artifacts
    }
    rows = []
    for detail in details:
        if detail["correct_candidate_generated"]:
            continue
        key = (detail["document_id"], detail["field_name"])
        artifact = artifacts_by_key[key]
        failed = [
            {
                "engine": row["engine"],
                "model": row["model_name"],
                "variant": row.get("preprocessing_variant"),
                "value": row.get("normalized_value"),
                "confidence": row.get("raw_confidence"),
            }
            for row in candidates
            if (row["document_id"], row["field_name"]) == key
        ]
        values = {str(row["value"]) for row in failed if row["value"]}
        critical = key[1] in {
            "patient_first", "patient_last", "insured_first", "insured_last",
            "member_id", "patient_dob",
        }
        low_confidence = all(
            float(row.get("confidence") or 0.0) < 0.75 for row in failed
        )
        priority = (
            100 * int(critical)
            + 30 * int(len(values) > 1)
            + 20 * int(low_confidence)
            + 10 * int(artifact["writing_type"] in {"HANDWRITTEN", "MIXED"})
        )
        rows.append({
            "dataset_version": "claims-handwriting-active-learning-v1",
            "document_id": key[0],
            "writer_group": f"DOCUMENT::{key[0]}",
            "field_name": key[1],
            "field_type": artifact["field_type"],
            "writing_type": artifact["writing_type"],
            "crop_reference": artifact["original_regional_crop"],
            "crop_sha256": artifact["image_sha256"],
            "preprocessing_metadata": artifact["preprocessing_metadata"],
            "failed_ocr_candidates": failed,
            "approved_transcription": None,
            "reviewer": None,
            "validator": None,
            "second_approval_required": True,
            "status": "AWAITING_REVIEW",
            "priority": priority,
            "split": split_for(key[0]),
            "evaluation_truth_exported": False,
        })
    rows.sort(key=lambda row: (-row["priority"], row["document_id"], row["field_name"]))
    output = RESULTS / "handwriting_active_learning"
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    document_splits: dict[str, set[str]] = {}
    for row in rows:
        document_splits.setdefault(row["document_id"], set()).add(row["split"])
    metrics = {
        "policy_version": "active-learning-v1",
        "unresolved_crops": len(rows),
        "approved_crops": 0,
        "training": sum(row["split"] == "training" for row in rows),
        "validation": sum(row["split"] == "validation" for row in rows),
        "holdout": sum(row["split"] == "holdout" for row in rows),
        "document_split_leakage": sum(
            len(splits) > 1 for splits in document_splits.values()
        ),
        "fine_tuning_enabled": False,
        "fine_tuning_blocker": (
            "requires >=100 approved diverse crops across >=3 families"
        ),
        "ground_truth_exported_as_training_label": False,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
