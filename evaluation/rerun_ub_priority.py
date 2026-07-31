"""Invalidate and rerun only the two expanded UB tax-ID regional crops."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from evaluation.schemas import GroundTruthDataset
from packages.templates.registry import TemplateRegistry
from workers.field_candidates.parsers import parse_alternatives
from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter

DOCUMENTS = ("C-02", "C-05")
PADDING_VERSION = "ub-tax-id-right-pad-v2"
PROFILE_VERSION = "numeric-identifier-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument("--manifest", type=Path, default=Path("evaluation_data/document_manifest.json"))
    parser.add_argument("--truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/ub_priority"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    truth = GroundTruthDataset.model_validate_json(args.truth.read_text(encoding="utf-8"))
    truth_docs = {document.document_id: document for document in truth.documents}
    template = TemplateRegistry.load_from_directory().get("ub04", "2014")
    region = template.field_region("federal_tax_id")
    assert region is not None
    crops = []
    records = []
    for document_id in DOCUMENTS:
        metadata = manifest[document_id]
        with Image.open(args.dataset / metadata["file_name"]) as source_file:
            source_file.seek(metadata["page_number"] - 1)
            source = source_file.convert("RGB")
        scale_x = source.width / template.reference_dimensions.width_px
        scale_y = source.height / template.reference_dimensions.height_px
        box = (
            max(0, int(region.x0 * scale_x) - 5),
            max(0, int(region.y0 * scale_y) - 5),
            min(source.width, int(region.x1 * scale_x) + 18),
            min(source.height, int(region.y1 * scale_y) + 5),
        )
        crop = source.crop(box)
        image_hash = hashlib.sha256(source.tobytes()).hexdigest()
        cache_identity = hashlib.sha256(
            (
                f"{image_hash}|{box}|{PADDING_VERSION}|{PROFILE_VERSION}|"
                "trocr-base-printed|microsoft/trocr-base-printed"
            ).encode()
        ).hexdigest()
        target = args.output / document_id
        target.mkdir(parents=True, exist_ok=True)
        crop.save(target / "federal_tax_id.expanded.png")
        cache = args.output / "cache" / f"{cache_identity}.json"
        record = {
            "document_id": document_id,
            "box": box,
            "image_hash": image_hash,
            "cache_identity": cache_identity,
            "cache_path": cache,
            "crop": crop,
        }
        if cache.is_file():
            record["ocr"] = json.loads(cache.read_text(encoding="utf-8"))
        else:
            crops.append(crop)
        records.append(record)
    if crops:
        adapter = TrOCRAdapter("microsoft/trocr-base-printed", min_confidence=0.0)
        results = adapter.recognize_batch(crops)
        result_iter = iter(results)
        for record in records:
            if "ocr" in record:
                continue
            result = next(result_iter)
            payload = {
                "text": result.text,
                "confidence": result.confidence,
                "engine": "trocr",
                "model_name": adapter.model_name,
                "model_version": "huggingface-checkpoint",
            }
            cache = record["cache_path"]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            record["ocr"] = payload
    output = []
    for record in records:
        expected = next(
            field.expected_raw for field in truth_docs[record["document_id"]].fields
            if field.field_name == "federal_tax_id"
        )
        alternatives = parse_alternatives(
            "federal_tax_id", record["ocr"].get("text") or ""
        )
        output.append({
            key: value for key, value in record.items()
            if key not in {"crop", "cache_path"}
        } | {
            "expected_evaluation_value": expected,
            "normalized_candidates": [value for value, _ in alternatives],
            "coverage_match": any(value == expected for value, _ in alternatives),
            "accepted": False,
            "validation_result": "NEEDS_REVIEW",
        })
    (args.output / "tax_id_results.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
