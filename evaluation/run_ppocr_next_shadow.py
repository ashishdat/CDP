"""Run PP-OCRv5/v6 shadow inference without loading evaluation truth."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path

import psutil
from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRRequest
from workers.cascade.ppocr_next_adapter import (
    PPOCRNextRecognitionEngine,
    PaddleTextRecognitionBackend,
)

MODELS = ("PP-OCRv6_medium_rec", "PP-OCRv5_server_rec")
PROFILES = (
    ("original", 16, 2),
    ("clahe", 16, 3),
    ("adaptive_threshold", 20, 3),
    ("sharpen", 16, 3),
)


def _resolve_crop_path(artifact: dict, manifest_path: Path) -> Path:
    """Resolve normalized artifacts across Windows hosts and Linux workers."""
    recorded = Path(str(artifact["original_regional_crop"]).replace("\\", "/"))
    if recorded.is_file():
        return recorded
    portable = (
        manifest_path.parent
        / artifact["document_id"]
        / artifact["field_name"]
        / recorded.name
    )
    if portable.is_file():
        return portable
    raise FileNotFoundError(
        f"crop not found at recorded path {recorded!s} or portable path {portable!s}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("evaluation_results/ocr_shadow_bakeoff/normalized_crops/artifacts.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation_results/ocr_shadow_bakeoff/inference"),
    )
    args = parser.parse_args()
    artifacts = json.loads(args.artifacts.read_text())
    config_path = Path("config/ocr_shadow_cascade_v2_2.yaml")
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    rows = []
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    backends = {model: PaddleTextRecognitionBackend(model) for model in MODELS}
    engines = [
        PPOCRNextRecognitionEngine(
            model_name=model,
            preprocessing_profile=profile,
            border_px=border,
            scale=scale,
            backend=backends[model],
        )
        for model in MODELS
        for profile, border, scale in PROFILES
    ]
    for artifact in artifacts:
        crop_path = _resolve_crop_path(artifact, args.artifacts)
        with Image.open(crop_path) as source:
            image = source.convert("RGB")
        x0, y0, x1, y1 = artifact["source_bbox"]
        request = OCRRequest(
            document_id=artifact["document_id"],
            page_number=1,
            field_name=artifact["field_name"],
            field_type=artifact["field_type"],
            form_type=ClaimFormType.UNSTRUCTURED,
            image=image,
            bounding_box=BoundingBox(
                x0=x0, y0=y0, x1=x1, y1=y1,
                image_width=max(int(x1), image.width),
                image_height=max(int(y1), image.height),
            ),
        )
        for engine in engines:
            started = time.perf_counter()
            try:
                candidate = engine.recognize(request)[0]
                failure = None
                payload = {
                    "raw_value": candidate.raw_value,
                    "normalized_value": candidate.value,
                    "raw_confidence": candidate.raw_confidence,
                    "latency_ms": candidate.latency_ms,
                    "validation_results": list(candidate.validation_results),
                }
            except Exception as exc:  # noqa: BLE001 - persist provider failure
                failure = f"{type(exc).__name__}: {exc}"
                payload = {
                    "raw_value": None, "normalized_value": None,
                    "raw_confidence": 0.0,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "validation_results": [],
                }
            peak_rss = max(peak_rss, process.memory_info().rss)
            rows.append({
                "document_id": artifact["document_id"],
                "field_name": artifact["field_name"],
                "image_sha256": artifact["image_sha256"],
                "engine": engine.engine_name,
                "independence_group": "PADDLE_FAMILY",
                "model_name": engine.model_name,
                "model_version": engine.model_version,
                "adapter_version": engine.provider_version,
                "preprocessing_variant": (
                    candidate.preprocessing_variant if failure is None else None
                ),
                "configuration_sha256": config_hash,
                "candidate_authority": "REVIEW_ONLY",
                "failure_reason": failure,
                **payload,
            })
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "candidates.json").write_text(json.dumps(rows, indent=2))
    runtime = {
        "python_version": platform.python_version(),
        "paddleocr_version": importlib.metadata.version("paddleocr"),
        "paddlepaddle_version": importlib.metadata.version("paddlepaddle"),
        "models": list(MODELS),
        "preprocessing_profiles": [profile for profile, _, _ in PROFILES],
        "device_backend": "paddle-default",
        "adapter_version": PPOCRNextRecognitionEngine.provider_version,
        "configuration_sha256": config_hash,
        "peak_rss_bytes": peak_rss,
        "fields_in_manifest": len(artifacts),
        "fields_attempted": len({(row["document_id"], row["field_name"]) for row in rows}),
        "candidate_records": len(rows),
        "evaluation_truth_loaded": False,
    }
    (args.output / "runtime.json").write_text(json.dumps(runtime, indent=2))
    print(json.dumps(runtime, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
