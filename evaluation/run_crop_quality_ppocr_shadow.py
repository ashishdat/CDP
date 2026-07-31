"""Run isolated PP-OCRv5/v6 recognition over the 30 crop-quality artifacts."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRRequest
from workers.cascade.ppocr_next_adapter import (
    PaddleTextRecognitionBackend,
    PPOCRNextRecognitionEngine,
)

PILOT = Path("/pilot")
MODELS = ("PP-OCRv6_medium_rec", "PP-OCRv5_server_rec")
PROFILES = (("original", 16, 2), ("clahe", 16, 3))


def main() -> int:
    manifest = [
        json.loads(line)
        for line in (PILOT / "pilot_manifest.jsonl").read_text().splitlines()
        if line.strip()
    ]
    backends = {name: PaddleTextRecognitionBackend(name) for name in MODELS}
    engines = [
        PPOCRNextRecognitionEngine(
            model_name=model, preprocessing_profile=profile, border_px=border,
            scale=scale, backend=backends[model],
        )
        for model in MODELS for profile, border, scale in PROFILES
    ]
    rows = []
    for item in manifest:
        crop_path = PILOT / "crops" / item["document_id"] / Path(
            str(item["crop_path"]).replace("\\", "/")
        ).name
        with Image.open(crop_path) as source:
            image = source.convert("RGB")
        request = OCRRequest(
            document_id=item["document_id"], page_number=item["page_number"],
            field_name=item["semantic_field_name"], field_type=item["data_type"],
            form_type=ClaimFormType.UNSTRUCTURED, image=image,
            bounding_box=BoundingBox(
                x0=0, y0=0, x1=image.width, y1=image.height,
                image_width=image.width, image_height=image.height,
            ),
        )
        for engine in engines:
            started = time.perf_counter()
            try:
                candidate = engine.recognize(request)[0]
                failure = None
                raw, confidence = candidate.raw_value, candidate.raw_confidence
                variant = candidate.preprocessing_variant
            except Exception as exc:  # noqa: BLE001
                raw, confidence, variant = None, 0.0, None
                failure = f"{type(exc).__name__}: {exc}"
            rows.append({
                "candidate_id": item["candidate_id"], "document_id": item["document_id"],
                "field_name": item["semantic_field_name"], "crop_sha256": item["crop_sha256"],
                "engine": engine.engine_name, "model": engine.model_name,
                "model_version": engine.model_version, "independence_group": "PADDLE_FAMILY",
                "preprocessing_variant": variant, "raw_value": raw,
                "raw_confidence": confidence,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "failure_reason": failure or ("NO_EVIDENCE" if not raw else None),
                "candidate_authority": "REVIEW_ONLY", "evaluation_truth_loaded": False,
            })
    output = PILOT / "ocr_shadow"
    output.mkdir(exist_ok=True)
    (output / "ppocr_candidates.json").write_text(json.dumps(rows, indent=2))
    runtime = {
        "manifest_fields": len(manifest),
        "fields_attempted": len({row["candidate_id"] for row in rows}),
        "candidate_records": len(rows),
        "fields_with_response": len({row["candidate_id"] for row in rows if row["raw_value"]}),
        "models": list(MODELS), "evaluation_truth_loaded": False,
        "candidate_authority": "REVIEW_ONLY",
    }
    (output / "ppocr_runtime.json").write_text(json.dumps(runtime, indent=2))
    print(json.dumps(runtime, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
