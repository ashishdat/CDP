"""Create provenance-preserving retuned variants for unresolved OCR crops."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from workers.field_candidates.crop_retuning import retune_cell_crop


def main() -> int:
    source = Path("evaluation_results/ocr_shadow_bakeoff/normalized_crops/artifacts.json")
    output = Path("evaluation_results/crop_retuning_v1")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    for artifact in artifacts:
        crop_path = Path(artifact["original_regional_crop"])
        with Image.open(crop_path) as image:
            tuned = retune_cell_crop(image.convert("RGB"))
        destination = output / artifact["document_id"] / artifact["field_name"] / "border_aware.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        tuned.image.save(destination)
        x0, y0, x1, y1 = artifact["source_bbox"]
        left, top, right, bottom = tuned.inset
        rows.append({**artifact,
            "original_regional_crop": str(destination),
            "parent_crop": str(crop_path),
            "source_bbox": [x0 + left, y0 + top, x1 - right, y1 - bottom],
            "crop_retuning": {"policy": "border_aware_v1", "inset": list(tuned.inset),
                "removed_rule_edges": list(tuned.removed_rule_edges), "changed": tuned.changed,
                "white_border_px": 16},
            "image_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        })
    (output / "artifacts.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    metrics = {"fields_processed": len(rows),
        "border_contaminated_fields": sum(row["crop_retuning"]["changed"] for row in rows),
        "artifact_completeness": len(rows) == len(artifacts), "production_promoted": False}
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
