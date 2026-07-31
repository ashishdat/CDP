"""Combine repeated same-person name regions for recognition agreement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def main() -> int:
    page_path = Path("evaluation_results/assets/A-06.png")
    output = Path("evaluation_results/duplicate_name_evidence")
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(page_path) as page:
        patient = page.crop((20, 320, 465, 375)).convert("L")
        insured = page.crop((1015, 320, 1710, 375)).convert("L")
    target_width = max(patient.width, insured.width)
    canvas = Image.new("L", (target_width, patient.height + insured.height + 20), 255)
    canvas.paste(patient, (0, 0))
    canvas.paste(insured, (0, patient.height + 20))
    canvas = ImageEnhance.Contrast(canvas).enhance(1.5)
    canvas = canvas.resize((canvas.width * 3, canvas.height * 3), Image.Resampling.LANCZOS)
    canvas = ImageOps.expand(canvas.filter(ImageFilter.SHARPEN), border=24, fill=255)
    crop_path = output / "A-06_patient_last_repeated.png"
    canvas.save(crop_path)
    artifact = {
        "document_id": "A-06", "field_name": "patient_last", "field_type": "name",
        "original_page_reference": str(page_path), "source_bbox": [20, 320, 1710, 375],
        "aligned_bbox": [20, 320, 1710, 375],
        "original_regional_crop": str(crop_path), "writing_type": "HANDWRITTEN",
        "crop_quality": {"repeated_identity_regions": 2},
        "preprocessing_metadata": {
            "profile": "repeated_name_upscale_v1", "upscale": 3,
            "contrast": 1.5, "sharpen": True,
        },
        "image_sha256": hashlib.sha256(crop_path.read_bytes()).hexdigest(),
        "evidence_lineage": {
            "source_kind": "REPEATED_SAME_PERSON_REGIONAL_EVIDENCE",
            "relationship_code": "01", "evaluation_truth_used": False,
        },
    }
    (output / "artifacts.json").write_text(
        json.dumps([artifact], indent=2), encoding="utf-8"
    )
    print(json.dumps({"artifacts": 1, "truth_loaded": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
