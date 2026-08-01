"""Run pinned GOT-OCR2 over unresolved crops without loading truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from PIL import Image

from workers.cascade.got_ocr2_adapter import GOTOCR2Adapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/got_ocr2_shadow.yaml"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    jobs = json.loads(Path(config["input_manifest"]).read_text(encoding="utf-8"))
    output = Path(config["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    candidates_path = output / "candidates.json"
    results = (json.loads(candidates_path.read_text(encoding="utf-8"))
               if args.resume and candidates_path.exists() else [])
    completed = {(row["document_id"], row["field_name"]) for row in results}
    pending = [job for job in jobs
               if (job["document_id"], job["field_name"]) not in completed]
    if args.limit is not None:
        pending = pending[:args.limit]
    adapter = GOTOCR2Adapter(config["model_name"], config["model_revision"],
        config.get("device", "auto"), float(config.get("min_confidence", 0.55)),
        int(config.get("max_new_tokens", 128)))
    for index, job in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] {job['document_id']}:{job['field_name']}", flush=True)
        crop_path = Path(job["normalized_crop"])
        started = time.perf_counter()
        try:
            with Image.open(crop_path) as image:
                result = adapter.recognize(image)
            row = {"document_id": job["document_id"], "field_name": job["field_name"],
                "crop_path": str(crop_path), "crop_sha256": hashlib.sha256(crop_path.read_bytes()).hexdigest(),
                "engine": "got_ocr2", "model_name": config["model_name"],
                "model_revision": config["model_revision"], "value": result.text,
                "confidence": result.confidence, "insufficient_evidence": result.insufficient_evidence,
                "candidate_authority": "REVIEW_ONLY", "ground_truth_loaded": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3), "failure_reason": None}
        except (OSError, RuntimeError, ValueError) as exc:
            row = {"document_id": job["document_id"], "field_name": job["field_name"],
                "crop_path": str(crop_path), "engine": "got_ocr2", "model_name": config["model_name"],
                "model_revision": config["model_revision"], "value": None, "confidence": 0.0,
                "insufficient_evidence": True, "candidate_authority": "REVIEW_ONLY",
                "ground_truth_loaded": False, "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "failure_reason": type(exc).__name__}
        results.append(row)
        candidates_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"  value={row['value']!r} latency_ms={row['latency_ms']}", flush=True)
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
