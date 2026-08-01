"""Run local Florence-2 over unresolved crop artifacts without loading truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from PIL import Image

from workers.cascade.florence2_adapter import Florence2Adapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/florence2_shadow.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not config.get("enabled"):
        print(json.dumps({"status": "DISABLED"}))
        return 0
    manifest_path = Path(config["input_manifest"])
    jobs = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = Path(config["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    adapter = Florence2Adapter(config["model_name"], config.get("model_revision"),
        config.get("device", "auto"), float(config.get("min_confidence", 0.55)))
    results = []
    for job in jobs:
        crop_path = Path(job["normalized_crop"])
        started = time.perf_counter()
        try:
            with Image.open(crop_path) as image:
                result = adapter.recognize(image)
            row = {"document_id": job["document_id"], "field_name": job["field_name"],
                "crop_path": str(crop_path), "crop_sha256": hashlib.sha256(crop_path.read_bytes()).hexdigest(),
                "engine": "florence2", "model_name": config["model_name"],
                "model_revision": config.get("model_revision"), "value": result.text,
                "confidence": result.confidence, "insufficient_evidence": result.insufficient_evidence,
                "candidate_authority": "REVIEW_ONLY", "ground_truth_loaded": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3), "failure_reason": None}
        except (OSError, RuntimeError, ValueError) as exc:
            row = {"document_id": job["document_id"], "field_name": job["field_name"],
                "crop_path": str(crop_path), "engine": "florence2", "model_name": config["model_name"],
                "value": None, "confidence": 0.0, "insufficient_evidence": True,
                "candidate_authority": "REVIEW_ONLY", "ground_truth_loaded": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "failure_reason": type(exc).__name__}
        results.append(row)
    (output / "candidates.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    metrics = {"fields_attempted": len(results), "ocr_responses": sum(bool(row["value"]) for row in results),
        "insufficient_evidence": sum(row["insufficient_evidence"] for row in results),
        "runtime_failures": sum(bool(row["failure_reason"]) for row in results),
        "candidate_authority": "REVIEW_ONLY", "ground_truth_loaded": False,
        "generated_at": datetime.now(UTC).isoformat()}
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
