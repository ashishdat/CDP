"""Run pinned PaddleOCR-VL on crops without exposing evaluation truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import yaml
from PIL import Image

from workers.cascade.paddleocr_vl_adapter import PaddleOCRVLAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/paddleocr_vl_shadow.yaml"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    jobs = json.loads(Path(config["input_manifest"]).read_text(encoding="utf-8"))
    output = Path(config["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    path = output / "candidates.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if args.resume and path.exists() else []
    done = {(row["document_id"], row["field_name"]) for row in rows}
    pending = [job for job in jobs if (job["document_id"], job["field_name"]) not in done]
    pending = pending[:args.limit] if args.limit is not None else pending
    adapter = PaddleOCRVLAdapter(config["model_name"], config["model_revision"],
        config.get("device", "auto"), int(config.get("max_new_tokens", 64)))
    for index, job in enumerate(pending, 1):
        print(f"[{index}/{len(pending)}] {job['document_id']}:{job['field_name']}", flush=True)
        crop_path = Path(job["normalized_crop"])
        started = time.perf_counter()
        try:
            with Image.open(crop_path) as image:
                result = adapter.recognize(image)
            value, failure = result.text, None
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            value, failure = None, f"{type(exc).__name__}: {exc}"
        row = {"document_id": job["document_id"], "field_name": job["field_name"],
            "crop_path": str(crop_path), "crop_sha256": hashlib.sha256(crop_path.read_bytes()).hexdigest(),
            "engine": config["engine"], "model_revision": config["model_revision"],
            "value": value, "candidate_authority": "REVIEW_ONLY",
            "ground_truth_loaded": False, "failure_reason": failure,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3)}
        rows.append(row)
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"  value={value!r} latency_ms={row['latency_ms']}", flush=True)
    metrics = {"fields_attempted": len(rows), "ocr_responses": sum(bool(r["value"]) for r in rows),
        "runtime_failures": sum(bool(r["failure_reason"]) for r in rows),
        "candidate_authority": "REVIEW_ONLY", "ground_truth_loaded": False}
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
