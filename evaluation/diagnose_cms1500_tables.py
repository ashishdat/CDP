"""Truth-free diagnostics for all CMS-1500 table regions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def _line_visibility(path: Path) -> dict:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return {"score": 0.0, "horizontal": 0, "vertical": 0}
    clahe = cv2.createCLAHE(2.0, (8, 8)).apply(image)
    binary = cv2.adaptiveThreshold(
        clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 10,
    )
    horizontal = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, image.shape[1] // 20), 1)),
    )
    vertical = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, image.shape[0] // 10))),
    )
    h = int(np.count_nonzero(horizontal))
    v = int(np.count_nonzero(vertical))
    return {"score": (h + v) / max(1, image.size), "horizontal": h, "vertical": v}


def main() -> int:
    records = json.loads(
        Path("evaluation_results/img2table_shadow/artifacts.json").read_text()
    )
    output = Path("evaluation_results/table_shadow_v2/cms1500_diagnostics")
    output.mkdir(parents=True, exist_ok=True)
    diagnostics = []
    for record in (row for row in records if row["family"] == "CMS1500"):
        crop = Path(record["crop_path"])
        visibility = _line_visibility(crop)
        if record.get("failure_reason"):
            failure = "PROVIDER_ERROR"
        elif record.get("tables"):
            failure = None
        elif visibility["score"] < 0.01:
            failure = "LOW_CONTRAST_LINES"
        else:
            failure = "NO_TABLE_STRUCTURE"
        diagnostic_copy = output / f"{record['document_id']}-region.png"
        diagnostic_copy.write_bytes(crop.read_bytes())
        diagnostics.append({
            "document_id": record["document_id"],
            "page_number": 1,
            "expected_region": record["source_bbox"],
            "input_image_hash": hashlib.sha256(
                Path(record["source_image"]).read_bytes()
            ).hexdigest(),
            "template_family_version": "CMS1500-02-12",
            "alignment_transformation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "crop_coordinates": record["source_bbox"],
            "crop_dimensions": [
                record["crop_quality"]["width"], record["crop_quality"]["height"]
            ],
            "image_quality": record["crop_quality"],
            "ruling_line_visibility": visibility,
            "table_detection_result": bool(record.get("tables")),
            "failure_reason": failure,
            "diagnostic_image": str(diagnostic_copy),
            "deterministic_improvements_attempted": [
                "CLAHE_LINE_DETECTION", "HORIZONTAL_VERTICAL_MORPHOLOGY"
            ],
        })
    (output / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
    print(json.dumps({
        "cms1500_regions": len(diagnostics),
        "detected": sum(item["table_detection_result"] for item in diagnostics),
        "undetected": sum(not item["table_detection_result"] for item in diagnostics),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
