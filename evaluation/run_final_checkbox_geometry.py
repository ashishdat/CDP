"""Resolve CMS relationship marks after aligning each page to the template frame."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from workers.field_candidates.mark_detection import detect_option_mark
from workers.page_detection.template_alignment import align_to_reference

RELATIONSHIP_BOX = (635, 400, 1015, 448)
OPTION_BOXES = {
    "01": (62, 14, 103, 48),
    "02": (161, 14, 202, 48),
    "03": (239, 14, 280, 48),
    "04": (337, 14, 378, 48),
}


def _relationship(crop: Image.Image) -> tuple[str, dict]:
    result = detect_option_mark(
        crop, OPTION_BOXES, minimum_score=0.12, minimum_margin=0.05,
        multiple_selection_threshold=0.15, border_inset=6,
    )
    return result.selected_option or "", {
        "option_scores": result.option_scores,
        "winning_margin": result.winning_margin,
        "ambiguous": result.ambiguous,
    }


def main() -> int:
    output = Path("evaluation_results/final_four_geometry")
    output.mkdir(parents=True, exist_ok=True)
    reference_path = Path("evaluation_results/assets/A-01.png")
    rows = []
    with Image.open(reference_path) as reference:
        for document_id in ("A-11", "D-03"):
            regional_path = Path(
                "evaluation_results/ocr_shadow_bakeoff/normalized_crops"
            ) / document_id / "rel_code/original.png"
            with Image.open(regional_path) as regional:
                regional_value, regional_diagnostics = _relationship(regional)
            if regional_value:
                rows.append({
                    "document_id": document_id, "field_name": "rel_code",
                    "value": regional_value, "status": "PIXEL_MARK_DETECTION",
                    "crop_path": str(regional_path),
                    **regional_diagnostics,
                    "evaluation_truth_loaded": False,
                })
                continue
            page_path = Path(f"evaluation_results/assets/{document_id}.png")
            with Image.open(page_path) as page:
                aligned = align_to_reference(page, reference)
                if not aligned.accepted or aligned.warped is None:
                    rows.append({
                        "document_id": document_id, "field_name": "rel_code",
                        "value": None, "status": "ALIGNMENT_REJECTED",
                        "alignment_score": aligned.alignment_score,
                        "reprojection_error": aligned.reprojection_error,
                    })
                    continue
                crop = aligned.warped.crop(RELATIONSHIP_BOX)
                crop_path = output / f"{document_id}_rel_code.png"
                crop.save(crop_path)
                value, diagnostics = _relationship(crop)
                rows.append({
                    "document_id": document_id, "field_name": "rel_code",
                    "value": value,
                    "status": "PIXEL_MARK_DETECTION",
                    "alignment_score": aligned.alignment_score,
                    "reprojection_error": aligned.reprojection_error,
                    "crop_path": str(crop_path),
                    **diagnostics,
                    "evaluation_truth_loaded": False,
                })
    (output / "candidates.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
