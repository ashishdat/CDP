"""Apply config-driven family routing and anchor-relative extraction to Group D."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml
from PIL import Image

from evaluation.schemas import PredictionDataset
from workers.page_detection.text_extraction import TextLine
from workers.standard_form_extraction.structured_fields import parse_person_name
from workers.unstructured_extraction.anchor_cropper import extract_anchor_crops
from workers.unstructured_extraction.family_router import DocumentFamilyRouter


def _load_pages(source_name: str, inventory: Path) -> dict[int, list[TextLine]]:
    pages = {}
    for cache in inventory.glob(f"{source_name}.page-*.paddle.json"):
        match = re.search(r"\.page-(\d+)\.paddle\.json$", cache.name)
        if match:
            pages[int(match.group(1))] = [
                TextLine(**item) for item in json.loads(cache.read_text(encoding="utf-8"))
            ]
    return pages


def _lines_in_box(lines: list[TextLine], box: tuple[int, int, int, int]) -> list[TextLine]:
    x0, y0, x1, y1 = box
    return sorted(
        [
            line for line in lines
            if x0 <= (line.x0 + line.x1) / 2 <= x1
            and y0 <= (line.y0 + line.y1) / 2 <= y1
        ],
        key=lambda line: (line.y0, line.x0),
    )


def _inline_anchor_value(lines: list[TextLine], anchors: list[str]) -> str:
    for line in lines:
        lower = line.text.lower()
        for anchor in anchors:
            position = lower.find(anchor.lower())
            if position >= 0:
                trailing = line.text[position + len(anchor):].strip(" :-")
                if trailing:
                    return trailing
    return ""


def _name_near_anchor(lines: list[TextLine], anchors: list[str]) -> str:
    inline = _inline_anchor_value(lines, anchors)
    if inline:
        return inline
    anchor_lines = [
        line for line in lines
        if any(anchor.lower() in line.text.lower() for anchor in anchors)
    ]
    if not anchor_lines:
        return ""
    anchor = max(anchor_lines, key=lambda line: line.confidence)
    height = max(anchor.y1 - anchor.y0, 12)
    same_row = [
        line for line in lines
        if line.x0 > anchor.x1
        and abs((line.y0 + line.y1) / 2 - (anchor.y0 + anchor.y1) / 2) <= height
    ]
    if same_row:
        return min(same_row, key=lambda line: line.x0).text
    below = [
        line for line in lines
        if line.y0 >= anchor.y1 - 3
        and line.y0 <= anchor.y1 + height * 2.5
        and not any(term in line.text.lower() for term in ("patient", "name", "address"))
    ]
    return min(below, key=lambda line: (line.y0, line.x0)).text if below else ""


def _address_parts(text: str) -> dict[str, str]:
    rows = [row.strip(" ,.") for row in text.splitlines() if row.strip(" ,.")]
    result = {"addr1": "", "city": "", "state": "", "zip": ""}
    address_rows = [
        row for row in rows
        if re.search(r"\d", row)
        and not re.search(r"diagnosis|date of|client id|birth", row, re.IGNORECASE)
    ]
    if address_rows:
        result["addr1"] = address_rows[0].upper()
    for row in rows[1:] + rows:
        match = re.search(
            r"(?P<city>[A-Za-z .'-]+),?\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)",
            row,
        )
        if match:
            result.update({
                "city": match.group("city").strip().upper(),
                "state": match.group("state"),
                "zip": re.sub(r"\D", "", match.group("zip")),
            })
            break
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--predictions", type=Path, default=Path("evaluation_data/predictions_handwriting.json")
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument(
        "--inventory", type=Path, default=Path("evaluation_results/unstructured_inventory")
    )
    parser.add_argument(
        "--families", type=Path, default=Path("config/unstructured_document_families.yaml")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation_data/predictions_family_cascade.json")
    )
    args = parser.parse_args()
    predictions = PredictionDataset.model_validate_json(
        args.predictions.read_text(encoding="utf-8")
    )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    family_config = yaml.safe_load(args.families.read_text(encoding="utf-8"))
    router = DocumentFamilyRouter(family_config)
    prediction_by_id = {document.document_id: document for document in predictions.documents}

    for document_id, metadata in manifest.items():
        if metadata["form_type"] != "UNSTRUCTURED":
            continue
        source_name = Path(metadata["file_name"]).name
        pages = _load_pages(source_name, args.inventory)
        decision = router.route(pages)
        if decision.needs_review or decision.page_number is None or decision.family is None:
            continue
        with Image.open(args.dataset / metadata["file_name"]) as source:
            source.seek(decision.page_number - 1)
            page_image = source.convert("RGB")
        lines = pages[decision.page_number]
        spec = family_config["families"][decision.family]
        crops = extract_anchor_crops(page_image, lines, spec.get("fields", {}))
        crop_dir = Path("evaluation_results/field_crops") / document_id
        crop_dir.mkdir(parents=True, exist_ok=True)
        fields = {
            field.field_name: field for field in prediction_by_id[document_id].fields
        }
        name_crop = crops.get("patient_name")
        if name_crop:
            name_crop.crop.save(crop_dir / "patient_name_anchor.png", "PNG")
            anchors = spec["fields"]["patient_name"]["anchors"]
            raw_name = _name_near_anchor(lines, anchors)
            semantics = (
                "LAST_FIRST_MIDDLE"
                if decision.family == "cms1500_attachment"
                else "FIRST_MIDDLE_LAST"
            )
            parsed = parse_person_name(raw_name, semantics)
            for field_name, value in (
                ("patient_last", parsed.last),
                ("patient_first", parsed.first),
            ):
                if field_name in fields and value:
                    fields[field_name].raw_value = value.upper()
                    fields[field_name].confidence = name_crop.anchor_confidence
                    fields[field_name].extraction_method = "ANCHOR_RELATIVE_PADDLEOCR"
                    fields[field_name].accepted = False
                    fields[field_name].validation_result = "NEEDS_REVIEW"
                    fields[field_name].fallback_used = True
                    fields[field_name].metadata.update({
                        "document_family": decision.family,
                        "routed_page": decision.page_number,
                        "anchor": name_crop.anchor,
                        "disposition": "HUMAN_REVIEW_REQUIRED",
                        "disposition_reason": "person_name_requires_authoritative_reference_match",
                    })
        address_crop = crops.get("patient_address")
        if address_crop:
            address_crop.crop.save(crop_dir / "patient_address_anchor.png", "PNG")
            address_text = "\n".join(
                line.text for line in _lines_in_box(lines, address_crop.box)
            )
            address = _address_parts(address_text)
            for field_name, value in (
                ("patient_addr1", address["addr1"]),
                ("patient_city", address["city"]),
                ("patient_state", address["state"]),
                ("patient_zip", address["zip"]),
            ):
                if field_name in fields and value:
                    fields[field_name].raw_value = value
                    fields[field_name].confidence = address_crop.anchor_confidence
                    fields[field_name].extraction_method = "ANCHOR_RELATIVE_PADDLEOCR"
                    fields[field_name].accepted = False
                    fields[field_name].validation_result = "NEEDS_REVIEW"
                    fields[field_name].fallback_used = True
                    fields[field_name].metadata.update({
                        "document_family": decision.family,
                        "routed_page": decision.page_number,
                        "anchor": address_crop.anchor,
                        "disposition": "HUMAN_REVIEW_REQUIRED",
                    })
        print(document_id, decision.family, decision.page_number, f"{decision.score:.2f}")

    args.output.write_text(predictions.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
