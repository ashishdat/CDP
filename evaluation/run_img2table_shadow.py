"""Run table-only img2table/Tesseract extraction without evaluation truth."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cv2
import yaml
from img2table.document import Image as TableImage
from img2table.ocr import TesseractOCR
from PIL import Image

RESULTS = Path("evaluation_results")
POLICY_VERSION = "img2table-shadow-v1"
ATTACHMENT_FAMILIES = {
    "D-05": "laboratory_invoice",
    "D-06": "laboratory_invoice",
    "D-07": "statement",
}


def _region(template: str) -> tuple[float, float, float, float]:
    payload = yaml.safe_load(Path(template).read_text())
    region = payload["table_regions"][0]
    return region["x0"], region["y0"], region["x1"], region["y1"]


def _targets() -> list[tuple[str, str, tuple[float, float, float, float]]]:
    manifest = json.loads(Path("evaluation_data/document_manifest.json").read_text())
    regions = {
        "CMS1500": _region("config/layout_templates/cms1500.yaml"),
        "UB04": _region("config/layout_templates/ub_institutional.yaml"),
        "laboratory_invoice": _region(
            "config/layout_templates/laboratory_invoice.yaml"
        ),
        "statement": _region("config/layout_templates/statement.yaml"),
    }
    targets = []
    for document_id, metadata in manifest.items():
        family = metadata["form_type"]
        if family in {"CMS1500", "UB04"}:
            targets.append((document_id, family, regions[family]))
    for document_id, family in ATTACHMENT_FAMILIES.items():
        targets.append((document_id, family, regions[family]))
    return targets


def main() -> int:
    output = RESULTS / "img2table_shadow"
    crop_root = output / "crops"
    crop_root.mkdir(parents=True, exist_ok=True)
    ocr = TesseractOCR(n_threads=1, lang="eng", psm=6)
    records = []
    for document_id, family, region in _targets():
        source = RESULTS / "assets" / f"{document_id}.png"
        if not source.is_file():
            records.append({
                "document_id": document_id, "family": family,
                "status": "NO_SOURCE_IMAGE", "tables": [],
            })
            continue
        with Image.open(source) as page:
            width, height = page.size
            box = (
                round(region[0] * width), round(region[1] * height),
                round(region[2] * width), round(region[3] * height),
            )
            crop = page.convert("RGB").crop(box)
        crop_path = crop_root / document_id / "table.png"
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(crop_path)
        gray = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
        quality = {
            "nonwhite_ratio": float((gray < 245).sum() / max(1, gray.size)),
            "width": crop.width, "height": crop.height,
        }
        started = time.perf_counter()
        try:
            tables = TableImage(src=str(crop_path), detect_rotation=False).extract_tables(
                ocr=ocr,
                implicit_rows=False,
                implicit_columns=False,
                borderless_tables=family in ATTACHMENT_FAMILIES.values(),
                min_confidence=35,
            )
            failure = None
        except Exception as exc:  # noqa: BLE001 - shadow provider failures are persisted
            tables, failure = [], f"{type(exc).__name__}: {exc}"
        serialized = []
        for table_index, table in enumerate(tables):
            cells = []
            for row_index, row in enumerate(table.content.values()):
                for column_index, cell in enumerate(row):
                    cells.append({
                        "row": row_index, "column": column_index,
                        "value": cell.value,
                        "bbox": {
                            "x0": cell.bbox.x1 + box[0],
                            "y0": cell.bbox.y1 + box[1],
                            "x1": cell.bbox.x2 + box[0],
                            "y1": cell.bbox.y2 + box[1],
                        },
                    })
            serialized.append({
                "table_index": table_index,
                "bbox_local": {
                    "x0": table.bbox.x1,
                    "y0": table.bbox.y1,
                    "x1": table.bbox.x2,
                    "y1": table.bbox.y2,
                },
                "cells": cells,
            })
        records.append({
            "document_id": document_id,
            "family": family,
            "source_image": str(source),
            "source_bbox": box,
            "crop_path": str(crop_path),
            "crop_sha256": hashlib.sha256(crop_path.read_bytes()).hexdigest(),
            "crop_quality": quality,
            "provider": "img2table+tesseract",
            "provider_version": POLICY_VERSION,
            "candidate_authority": "REVIEW_ONLY",
            "latency_ms": (time.perf_counter() - started) * 1000,
            "failure_reason": failure,
            "tables": serialized,
            "evaluation_truth_loaded": False,
        })
    (output / "artifacts.json").write_text(json.dumps(records, indent=2))
    table_count = sum(len(row.get("tables", [])) for row in records)
    cell_count = sum(
        len(table["cells"]) for row in records
        for table in row.get("tables", [])
    )
    nonempty = sum(
        bool(str(cell.get("value") or "").strip()) for row in records
        for table in row.get("tables", []) for cell in table["cells"]
    )
    family_metrics = {}
    for family in sorted({row["family"] for row in records}):
        family_rows = [row for row in records if row["family"] == family]
        family_metrics[family] = {
            "regions_attempted": len(family_rows),
            "regions_completed": sum(
                not row.get("failure_reason") for row in family_rows
            ),
            "regions_with_tables": sum(
                bool(row.get("tables")) for row in family_rows
            ),
            "tables_detected": sum(
                len(row.get("tables", [])) for row in family_rows
            ),
            "cells_detected": sum(
                len(table["cells"]) for row in family_rows
                for table in row.get("tables", [])
            ),
        }
    metrics = {
        "policy_version": POLICY_VERSION,
        "regions_attempted": len(records),
        "regions_completed": sum(not row.get("failure_reason") for row in records),
        "tables_detected": table_count,
        "cells_detected": cell_count,
        "nonempty_cells": nonempty,
        "table_region_coverage": sum(bool(row.get("tables")) for row in records)
        / max(1, len(records)),
        "by_family": family_metrics,
        "production_header_accuracy_changed": False,
        "evaluation_truth_loaded": False,
        "candidate_authority": "REVIEW_ONLY",
    }
    (output / "runtime.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
