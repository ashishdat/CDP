"""Run review-only Tesseract OCR over the crop-quality pilot without truth."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cv2
from PIL import Image, ImageOps

from workers.cascade.tesseract_adapter import for_field_type

PILOT = Path("evaluation_results/table_crop_quality_pilot")
PROFILES = ("original", "upscale_2x", "clahe", "adaptive_threshold")


def _variant(image: Image.Image, profile: str) -> Image.Image:
    gray = ImageOps.grayscale(image)
    if profile == "original":
        return image
    if profile == "upscale_2x":
        return image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    array = cv2.cvtColor(__import__("numpy").array(gray), cv2.COLOR_GRAY2BGR)
    mono = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
    if profile == "clahe":
        result = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(mono)
    else:
        result = cv2.adaptiveThreshold(
            mono, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 11
        )
    return Image.fromarray(result)


def main() -> int:
    manifest = [
        json.loads(line)
        for line in (PILOT / "pilot_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows: list[dict] = []
    for item in manifest:
        crop_path = Path(str(item["crop_path"]).replace("\\", "/"))
        with Image.open(crop_path) as source:
            crop = source.convert("RGB")
        for profile in PROFILES:
            prepared = _variant(crop, profile)
            engine = for_field_type(item["data_type"])
            started = time.perf_counter()
            try:
                tokens = engine.extract(prepared)
                raw = " ".join(token.text for token in tokens).strip()
                confidence = (
                    sum(token.confidence for token in tokens) / len(tokens) if tokens else 0.0
                )
                failure = None
            except Exception as exc:  # noqa: BLE001 - provider failure is evidence
                raw, confidence = "", 0.0
                failure = f"{type(exc).__name__}: {exc}"
            rows.append(
                {
                    "candidate_id": item["candidate_id"],
                    "document_id": item["document_id"],
                    "field_name": item["semantic_field_name"],
                    "service_line_number": item["service_line_number"],
                    "crop_sha256": item["crop_sha256"],
                    "engine": engine.engine_name,
                    "model": engine.model_name,
                    "model_version": engine.model_version,
                    "independence_group": "TESSERACT_FAMILY",
                    "preprocessing_variant": profile,
                    "raw_value": raw or None,
                    "raw_confidence": confidence,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "failure_reason": failure or ("NO_EVIDENCE" if not raw else None),
                    "candidate_authority": "REVIEW_ONLY",
                    "evaluation_truth_loaded": False,
                }
            )
    output = PILOT / "ocr_shadow"
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidates.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    runtime = {
        "manifest_fields": len(manifest),
        "fields_attempted": len({row["candidate_id"] for row in rows}),
        "candidate_records": len(rows),
        "fields_with_response": len(
            {row["candidate_id"] for row in rows if row["raw_value"]}
        ),
        "profiles": list(PROFILES),
        "manifest_sha256": hashlib.sha256(
            (PILOT / "pilot_manifest.jsonl").read_bytes()
        ).hexdigest(),
        "evaluation_truth_loaded": False,
        "candidate_authority": "REVIEW_ONLY",
    }
    (output / "runtime.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    print(json.dumps(runtime, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
