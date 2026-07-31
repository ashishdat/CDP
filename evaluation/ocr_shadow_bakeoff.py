"""Create the controlled 23-field OCR shadow bake-off manifest and status."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


def main() -> int:
    pareto = json.loads(
        Path("evaluation_results/remaining_error_pareto/details.json").read_text()
    )
    jobs = []
    for row in pareto:
        document_id, field = row["document_id"], row["field_name"]
        crop_root = Path("evaluation_results/field_crops") / document_id
        crops = sorted(str(path) for path in crop_root.glob(f"{field}*.png"))
        jobs.append({
            "document_id": document_id,
            "field_name": field,
            "writing_type": row["writing_type"],
            "error_category": row["error_category"],
            "crop_paths": crops,
            "providers": {
                "ppocr_v4": "BASELINE_PERSISTED",
                "ppocr_v6_medium_rec": (
                    "READY" if importlib.util.find_spec("paddleocr") else "RUNTIME_UNAVAILABLE"
                ),
                "ppocr_v5_server_rec": (
                    "READY" if importlib.util.find_spec("paddleocr") else "RUNTIME_UNAVAILABLE"
                ),
                "azure_read": (
                    "READY"
                    if os.getenv("AZURE_DOCUMENT_INTELLIGENCE_AUTHORIZED") == "true"
                    else "DISABLED_AWAITING_PHI_AND_REGION_APPROVAL"
                ),
            },
            "inference_may_read_ground_truth": False,
            "candidate_authority": "REVIEW_ONLY",
        })
    output = Path("evaluation_results/ocr_shadow_bakeoff")
    output.mkdir(parents=True, exist_ok=True)
    normalized_metrics_path = output / "normalized_crops/metrics.json"
    normalized = (
        json.loads(normalized_metrics_path.read_text())
        if normalized_metrics_path.is_file()
        else {"normalized_artifacts": 0, "required_fields": len(jobs), "complete": False}
    )
    artifacts_path = output / "normalized_crops/artifacts.json"
    normalized_artifacts = (
        json.loads(artifacts_path.read_text()) if artifacts_path.is_file() else []
    )
    normalized_by_key = {
        (row["document_id"], row["field_name"]): row for row in normalized_artifacts
    }
    for job in jobs:
        artifact = normalized_by_key.get((job["document_id"], job["field_name"]))
        job["normalized_crop"] = artifact["original_regional_crop"] if artifact else None
        job["artifact_contract_complete"] = artifact is not None
    inference_path = output / "inference/runtime.json"
    inference = json.loads(inference_path.read_text()) if inference_path.is_file() else {}
    (output / "manifest.json").write_text(json.dumps(jobs, indent=2))
    metrics = {
        "policy_version": "ocr-shadow-cascade-v2.1",
        "target_fields": len(jobs),
        "jobs_with_source_crops": sum(bool(job["crop_paths"]) for job in jobs),
        "jobs_with_normalized_crops": sum(
            job["artifact_contract_complete"] for job in jobs
        ),
        "manifest_complete_fields": normalized["normalized_artifacts"],
        "manifest_completeness": (
            f"{normalized['normalized_artifacts']}/{normalized['required_fields']}"
        ),
        "model_attempted_fields": inference.get("fields_attempted", 0),
        "model_attempted_denominator": len(jobs),
        "ppocr_next_runtime_available": importlib.util.find_spec("paddleocr") is not None,
        "azure_authorized": os.getenv("AZURE_DOCUMENT_INTELLIGENCE_AUTHORIZED") == "true",
        "inference_completed": inference.get("fields_attempted", 0) == len(jobs),
        "evaluation_started": False,
        "critical_false_accepts": 0,
        "base_release_modified": False,
        "runtime_blocker": (
            None if inference
            else "PaddlePaddle 3.x has no Windows Python 3.14 wheel; "
            "Python 3.11 shadow container required"
        ),
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
