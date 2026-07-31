"""Normalize img2table artifacts into content-addressed cell evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PIL import Image, ImageDraw

from packages.storage.hashing import sha256_file
from packages.table_contracts import CellCandidate
from workers.table_extraction.normalization import normalize_cell

TABLE_TYPES = {
    "CMS1500": "CMS1500_SERVICE_LINES",
    "UB04": "UB04_SERVICE_LINES",
    "laboratory_invoice": "LABORATORY_RESULTS",
    "statement": "STATEMENT_LINES",
}
TEMPLATE_VERSIONS = {
    "CMS1500": "02-12",
    "UB04": "2014",
    "laboratory_invoice": "v1",
    "statement": "v1",
}


def normalize_artifacts(source: Path, root: Path, output: Path) -> int:
    records = json.loads(source.read_text(encoding="utf-8"))
    count = 0
    rejected = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            page_path = Path(record["source_image"])
            page_hash = sha256_file(str(page_path))
            address = root / page_hash
            address.mkdir(parents=True, exist_ok=True)
            stored_page = address / "original_page.png"
            if not stored_page.exists():
                shutil.copy2(page_path, stored_page)
            with Image.open(page_path) as page:
                overlay = page.convert("RGB")
                page_width, page_height = page.size
            drawing = ImageDraw.Draw(overlay)
            for table in record.get("tables", []):
                table_index = table["table_index"]
                table_local = table["bbox_local"]
                region = record["source_bbox"]
                table_bbox = (
                    table_local["x0"] + region[0], table_local["y0"] + region[1],
                    table_local["x1"] + region[0], table_local["y1"] + region[1],
                )
                drawing.rectangle(table_bbox, outline="blue", width=3)
                for cell in table["cells"]:
                    raw_bbox = tuple(cell["bbox"].values())
                    bbox = (
                        max(0, min(page_width, raw_bbox[0])),
                        max(0, min(page_height, raw_bbox[1])),
                        max(0, min(page_width, raw_bbox[2])),
                        max(0, min(page_height, raw_bbox[3])),
                    )
                    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                        rejected.append({
                            "document_id": record["document_id"],
                            "table_index": table_index,
                            "row_index": cell["row"],
                            "column_index": cell["column"],
                            "raw_bbox": raw_bbox,
                            "clamped_bbox": bbox,
                            "failure_reason": "INVALID_REGION",
                        })
                        continue
                    drawing.rectangle(bbox, outline="red", width=2)
            overlay_path = address / "grid_overlay.png"
            overlay.save(overlay_path)
            aligned_path = address / "aligned_page.png"
            if not aligned_path.exists():
                shutil.copy2(stored_page, aligned_path)
            for table in record.get("tables", []):
                table_local = table["bbox_local"]
                region = record["source_bbox"]
                table_bbox = (
                    table_local["x0"] + region[0], table_local["y0"] + region[1],
                    table_local["x1"] + region[0], table_local["y1"] + region[1],
                )
                table_index = table["table_index"]
                for cell in table["cells"]:
                    raw_bbox = tuple(cell["bbox"].values())
                    bbox = (
                        max(0, min(page_width, raw_bbox[0])),
                        max(0, min(page_height, raw_bbox[1])),
                        max(0, min(page_width, raw_bbox[2])),
                        max(0, min(page_height, raw_bbox[3])),
                    )
                    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                        continue
                    crop_name = hashlib.sha256(
                        f"{page_hash}:{bbox}".encode()
                    ).hexdigest() + ".png"
                    crop_path = address / "cells" / crop_name
                    crop_path.parent.mkdir(exist_ok=True)
                    if not crop_path.exists():
                        with Image.open(page_path) as page:
                            page.convert("RGB").crop(bbox).save(crop_path)
                    column = f"column_{cell['column']}"
                    normalized, transformation, validation, _acceptable = normalize_cell(
                        str(cell.get("value") or ""), column
                    )
                    identity = (
                        f"{record['document_id']}:{table_index}:"
                        f"{cell['row']}:{column}:{page_hash}"
                    )
                    candidate = CellCandidate(
                        candidate_id=uuid5(NAMESPACE_URL, identity),
                        document_id=record["document_id"],
                        page_number=1,
                        document_family=record["family"],
                        table_type=TABLE_TYPES[record["family"]],
                        table_bbox=table_bbox,
                        table_index=table_index,
                        row_index=cell["row"],
                        column_name=column,
                        cell_bbox=bbox,
                        raw_text=str(cell.get("value") or ""),
                        normalized_value=normalized,
                        confidence=0.0,
                        provider="img2table_tesseract",
                        provider_version=record["provider_version"],
                        template_version=TEMPLATE_VERSIONS[record["family"]],
                        preprocessing_profile="table_shadow_v2_original",
                        image_sha256=page_hash,
                        automatically_acceptable=False,
                        transformation_name=transformation,
                        validation_outcome=validation,
                        transformation_reason="Conservative column-specific normalization",
                        provenance={
                            "source_image": str(stored_page),
                            "aligned_page": str(aligned_path),
                            "table_region_crop": record["crop_path"],
                            "grid_overlay": str(overlay_path),
                            "cell_crop": str(crop_path),
                            "transform_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            "raw_ocr_provider": record["provider"],
                        },
                    )
                    handle.write(candidate.model_dump_json() + "\n")
                    count += 1
    (output.parent / "rejected_cells.json").write_text(
        json.dumps(rejected, indent=2), encoding="utf-8"
    )
    return count
