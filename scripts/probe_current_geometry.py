import json
import io
from zipfile import ZipFile
import cv2
import numpy as np
from PIL import Image
from pathlib import Path
from packages.templates.registry import TemplateRegistry
from packages.extraction_recovery.ub04_registered import extract_registered_ub04


def main():
    root = Path.cwd()
    inventory = json.loads((root / "evaluation_results/current_review_repairs/inventory.json").read_text())
    registry = TemplateRegistry.load_from_directory()
    for case in inventory["cases"]:
        if case["family"] != "UB04":
            continue
        ocr = json.loads((Path(case["artifact"]) / "ocr/OCRCandidates.json").read_text())
        geometry = Path(ocr["geometry_reference"]).parent
        saved = json.loads((geometry / "GeometryResult.json").read_text())
        telemetry = json.loads((geometry / "geometry_telemetry.json").read_text())
        template = registry.get(ocr["template_id"], ocr["template_version"])
        with registry.load_reference_image(template) as reference:
            with ZipFile(telemetry["source"]["archive"]) as archive:
                data = archive.read(telemetry["source"]["entry"])
            with Image.open(io.BytesIO(data)) as source:
                source.seek(saved["page_number"]-1)
                pixels = np.asarray(source.convert("L"))
            rectified = Image.fromarray(cv2.warpPerspective(pixels,
                np.asarray(saved["source_to_geometry_transform"]), reference.size, borderValue=255))
            rows, _, local = extract_registered_ub04(rectified, saved, template, reference,
                                                 lambda *args: ([], [], "PROBE_NO_OCR"))
            result = {"document": case["document"], "reference_size": reference.size,
                      "local_alignment": local,
                      "field_probes": [{"field": row["field"], "router_reason": row["router_reason"],
                                        "bbox": row["canonical_region"]} for row in rows]}
            table = template.service_line_region
            source_ink = np.asarray(rectified) < 180
            reference_ink = np.asarray(reference.convert("L")) < 180
            printed_neighborhood = cv2.dilate(reference_ink.astype(np.uint8), np.ones((7,7), np.uint8)) > 0
            counts = []
            for index in range(table.max_rows):
                y0 = round(table.table_y0+(table.table_y1-table.table_y0)*index/table.max_rows)+3
                y1 = round(table.table_y0+(table.table_y1-table.table_y0)*(index+1)/table.max_rows)-3
                bounds = (slice(y0,y1), slice(table.table_x0+3, table.table_x1-3))
                counts.append({"row":index+1, "literal_new_ink":int(np.count_nonzero(source_ink[bounds] & ~reference_ink[bounds])),
                               "new_ink_outside_printed_neighborhood":int(np.count_nonzero(source_ink[bounds] & ~printed_neighborhood[bounds]))})
            result["service_row_ink_probe"] = counts
            print(case["document"], "reference_size", reference.size,
                  "verified", [name for name, check in local["landmarks"].items() if check.get("accepted")])
            (root / "evaluation_results/current_review_repairs" / (case["document"].replace("/", "__")+".geometry_probe.json")).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
