"""Generate bounded complete-block candidates with component lineage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from workers.field_candidates.address_block import reconstruct_lines
from workers.field_candidates.name_interpretations import interpret_complete_name
from workers.retry.alternate_preprocessing import (
    adaptive_threshold, aggressive_contrast, remove_printed_lines, upscale,
)


def main() -> int:
    manifest = json.loads(Path("evaluation_data/document_manifest.json").read_text())
    output = Path("evaluation_results/expanded_blocks")
    candidates = []
    for document_id, metadata in manifest.items():
        if metadata["form_type"] != "CMS1500":
            continue
        ocr_path = Path(f"evaluation_results/assets/{document_id}.source-v2.ocr.json")
        image_path = Path(f"evaluation_results/assets/{document_id}.png")
        if not ocr_path.is_file() or not image_path.is_file():
            continue
        tokens = json.loads(ocr_path.read_text())
        with Image.open(image_path) as image:
            page = image.convert("RGB")
        candidates.extend(_name_candidates(document_id, metadata["page_number"], page, tokens, output))
        candidates.extend(_address_candidates(document_id, metadata["page_number"], page, tokens, output))
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidates.json").write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    print(json.dumps({"expanded_component_candidates": len(candidates)}, indent=2))
    return 0


def _save_variants(document_id, block_name, page, bbox, output):
    crop = page.crop(bbox)
    root = output / "crops" / document_id / block_name
    root.mkdir(parents=True, exist_ok=True)
    variants = {
        "original": crop, "upscale_2x": upscale(crop),
        "upscale_3x": crop.resize((crop.width * 3, crop.height * 3)),
        "clahe": aggressive_contrast(crop),
        "adaptive_threshold": adaptive_threshold(crop),
    }
    removed, safe, _loss = remove_printed_lines(crop)
    if safe:
        variants["line_removed"] = removed
    paths = {}
    for name, image in variants.items():
        path = root / f"{name}.png"
        image.save(path)
        paths[name] = str(path)
    return paths


def _base(document_id, page_number, field, value, derived_from, bbox, tokens, paths, parser):
    token_ids = [
        hashlib.sha256(
            f"{item['text']}|{item['x0']}|{item['y0']}|{item['x1']}|{item['y1']}".encode()
        ).hexdigest()[:16] for item in tokens
    ]
    return {
        "document_id": document_id, "field_name": field, "value": value,
        "normalized": value, "provider": "expanded_block_parser",
        "engine": "paddleocr", "model": "cached-page-regional",
        "preprocessing_variant": "original_plus_persisted_variants",
        "raw_confidence": min((item.get("confidence", 0.0) for item in tokens), default=0.0),
        "calibrated_confidence": None,
        "validation_results": [f"complete_{derived_from}_component"],
        "regional_provenance": "EXPANDED_BLOCK",
        "derived_from": derived_from, "source_page": page_number,
        "source_bbox": {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]},
        "parser": parser, "parser_version": "1", "ocr_candidate_ids": token_ids,
        "crop_variants": paths, "accepted": False,
        "semantic_reference_status": "REFERENCE_UNAVAILABLE",
    }


def _name_candidates(document_id, page_number, page, tokens, output):
    # Persisted source-v2 OCR tokens are y-rebased to the top-form strip,
    # while crop pixels remain in the full 1712x2214 source-page frame.
    token_bbox = (55, 35, 610, 85)
    source_bbox = (55, 320, 625, 390)
    block = [
        item for item in tokens
        if token_bbox[0] <= item["x0"] <= token_bbox[2]
        and token_bbox[1] <= item["y0"] <= token_bbox[3]
    ]
    lines = reconstruct_lines(block)
    paths = _save_variants(document_id, "patient_name", page, source_bbox, output)
    result = []
    for line in lines:
        interpretations = interpret_complete_name(line, "LAST_FIRST")
        for parsed in interpretations[:1]:
            result.extend([
                _base(document_id, page_number, "patient_first", parsed.first.upper(),
                      "name_block", source_bbox, block, paths, "complete_name_parser"),
                _base(document_id, page_number, "patient_last", parsed.last.upper(),
                      "name_block", source_bbox, block, paths, "complete_name_parser"),
            ])
    return result


def _address_candidates(document_id, page_number, page, tokens, output):
    token_bbox = (1000, 75, 1600, 270)
    source_bbox = (1015, 385, 1710, 582)
    block = [
        item for item in tokens
        if token_bbox[0] <= item["x0"] <= token_bbox[2]
        and token_bbox[1] <= item["y0"] <= token_bbox[3]
    ]
    paths = _save_variants(
        document_id, "insured_address", page, source_bbox, output
    )
    labels = {"CITY", "STATE", "ZIP CODE", "INFORMATION"}
    slots = {
        "insured_addr1": [item for item in block if 95 <= item["y0"] <= 145],
        "insured_city": [
            item for item in block
            if 165 <= item["y0"] <= 210 and item["x0"] < 1450
        ],
        "insured_state": [
            item for item in block
            if 160 <= item["y0"] <= 210 and item["x0"] >= 1450
        ],
        "insured_zip": [
            item for item in block
            if 215 <= item["y0"] <= 260 and item["x0"] < 1250
        ],
    }
    result = []
    for field, items in slots.items():
        usable = [item for item in items if item["text"].strip().upper() not in labels]
        value = " ".join(item["text"].strip() for item in sorted(usable, key=lambda x: x["x0"])).strip()
        if field == "insured_zip":
            value = "".join(character for character in value if character.isdigit())
        if value:
            result.append(_base(
                document_id, page_number, field, value.upper(), "address_block",
                source_bbox, usable, paths, "complete_address_parser",
            ))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
