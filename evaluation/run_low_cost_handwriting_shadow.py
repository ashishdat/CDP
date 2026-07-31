"""Run generic TrOCR only on unresolved handwritten/mixed name/address crops."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from PIL import Image

from workers.cascade.line_segmentation import segment_text_lines
from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter


RESULTS = Path("evaluation_results")
MODEL = "microsoft/trocr-base-handwritten"
MODEL_ROUTE_VERSION = "low-cost-handwriting-shadow-v1"
ALLOWED_TYPES = {"name", "address"}
ALLOWED_WRITING = {"HANDWRITTEN", "MIXED"}


def resolve_crop(recorded: str, artifact: dict) -> Path:
    path = Path(recorded.replace("\\", "/"))
    if path.is_file():
        return path
    return (
        RESULTS / "ocr_shadow_bakeoff/normalized_crops"
        / artifact["document_id"] / artifact["field_name"] / path.name
    )


def main() -> int:
    evaluation = json.loads(
        (RESULTS / "ocr_shadow_bakeoff/evaluation/details.json").read_text()
    )
    unresolved = {
        (row["document_id"], row["field_name"])
        for row in evaluation if not row["correct_candidate_generated"]
    }
    artifacts = [
        row for row in json.loads(
            (RESULTS / "ocr_shadow_bakeoff/normalized_crops/artifacts.json").read_text()
        )
        if (row["document_id"], row["field_name"]) in unresolved
        and row["field_type"] in ALLOWED_TYPES
        and row["writing_type"] in ALLOWED_WRITING
    ]
    output = RESULTS / "low_cost_handwriting_shadow"
    cache = output / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    adapter = TrOCRAdapter(MODEL, device="auto", min_confidence=0.0)
    rows = []
    for artifact in artifacts:
        crop_path = resolve_crop(artifact["original_regional_crop"], artifact)
        cache_key = hashlib.sha256(
            f"{artifact['image_sha256']}|{MODEL}|{MODEL_ROUTE_VERSION}".encode()
        ).hexdigest()
        cache_path = cache / f"{cache_key}.json"
        if cache_path.is_file():
            payload = json.loads(cache_path.read_text())
        else:
            with Image.open(crop_path) as source:
                lines = segment_text_lines(source.convert("RGB"))
            started = time.perf_counter()
            results = adapter.recognize_batch(lines)
            payload = {
                "value": "\n".join(
                    result.text.strip() for result in results if result.text
                ) or None,
                "line_results": [result.__dict__ for result in results],
                "latency_ms": (time.perf_counter() - started) * 1000,
                "line_count": len(lines),
            }
            cache_path.write_text(json.dumps(payload, indent=2))
        rows.append({
            "document_id": artifact["document_id"],
            "field_name": artifact["field_name"],
            "field_type": artifact["field_type"],
            "writing_type": artifact["writing_type"],
            "crop_reference": str(crop_path),
            "crop_sha256": artifact["image_sha256"],
            "engine": "trocr",
            "independence_group": "TROCR_FAMILY",
            "model": MODEL,
            "model_route_version": MODEL_ROUTE_VERSION,
            "value": payload["value"],
            "line_results": payload["line_results"],
            "latency_ms": payload["latency_ms"],
            "candidate_authority": "REVIEW_ONLY",
            "accepted": False,
            "disposition": "HUMAN_REVIEW_REQUIRED",
            "evaluation_truth_loaded": False,
        })
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidates.json").write_text(json.dumps(rows, indent=2))
    metrics = {
        "unresolved_manifest_fields": len(unresolved),
        "eligible_handwriting_fields": len(artifacts),
        "fields_attempted": len(rows),
        "responses": sum(bool(row["value"]) for row in rows),
        "automatically_accepted": 0,
        "candidate_authority": "REVIEW_ONLY",
        "evaluation_truth_loaded": False,
    }
    (output / "runtime.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
