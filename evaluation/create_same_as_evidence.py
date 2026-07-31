"""Create alternate CMS evidence crops only when SELF relationship is proven."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from workers.field_candidates.mark_detection import detect_option_mark

RELATIONSHIP_BOX = (635, 400, 1015, 448)
OPTION_BOXES = {
    "01": (62, 14, 103, 48), "02": (161, 14, 202, 48),
    "03": (239, 14, 280, 48), "04": (337, 14, 378, 48),
}


def main() -> int:
    output = Path("evaluation_results/same_as_evidence")
    output.mkdir(parents=True, exist_ok=True)
    jobs = (
        ("A-01", "insured_state", "address", (555, 475, 635, 512)),
        ("A-06", "patient_last", "name", (1015, 320, 1710, 375)),
    )
    artifacts = []
    for document_id, field_name, field_type, evidence_box in jobs:
        page_path = Path(f"evaluation_results/assets/{document_id}.png")
        with Image.open(page_path) as page:
            relationship = page.crop(RELATIONSHIP_BOX)
            mark = detect_option_mark(
                relationship, OPTION_BOXES, minimum_score=0.12,
                minimum_margin=0.05, multiple_selection_threshold=0.15,
                border_inset=6,
            )
            if mark.selected_option != "01":
                raise RuntimeError(f"{document_id}: SELF relationship not proven")
            crop = page.crop(evidence_box)
            crop_path = output / f"{document_id}_{field_name}.png"
            crop.save(crop_path)
        artifacts.append({
            "document_id": document_id, "field_name": field_name,
            "field_type": field_type, "original_page_reference": str(page_path),
            "source_bbox": list(evidence_box), "aligned_bbox": list(evidence_box),
            "original_regional_crop": str(crop_path), "writing_type": "MIXED",
            "crop_quality": {"same_as_patient_verified": True},
            "preprocessing_metadata": {"profile": "same_as_patient_v1"},
            "image_sha256": hashlib.sha256(crop_path.read_bytes()).hexdigest(),
            "evidence_lineage": {
                "source_kind": "SAME_AS_PATIENT_ALTERNATE_REGIONAL_CROP",
                "relationship_method": "PIXEL_MARK_DETECTION",
                "relationship_code": "01", "evaluation_truth_used": False,
            },
        })
    manifest = output / "artifacts.json"
    manifest.write_text(json.dumps(artifacts, indent=2), encoding="utf-8")
    print(json.dumps({"artifacts": len(artifacts), "truth_loaded": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
