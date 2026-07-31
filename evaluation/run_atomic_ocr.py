"""Run the OCR cascade on validated, one-field-per-image template crops."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image

from evaluation.schemas import PredictedField, PredictionDataset, PredictionDocument
from packages.validation_rules.npi import is_valid_npi
from workers.cascade.cascading_ocr import CascadingOCR
from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.page_detection.text_extraction import PaddleOCRTextExtractor, TextLine

STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "NA",
}


def _joined(lines: list[TextLine]) -> tuple[str, float]:
    ordered = sorted(lines, key=lambda line: (line.y0, line.x0))
    text = " ".join(line.text for line in ordered).strip()
    confidence = sum(line.confidence for line in ordered) / len(ordered) if ordered else 0.0
    return text, confidence


def _person_part(text: str, first: bool) -> str:
    cleaned = re.sub(r"[^A-Za-z,.' -]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")
    parts = [part.strip(" .").upper() for part in cleaned.split(",", 1)]
    if len(parts) == 1:
        words = parts[0].split()
        parts = [words[0], " ".join(words[1:])] if words else [""]
    selected = parts[1 if first else 0] if len(parts) > (1 if first else 0) else ""
    if first:
        # The source crop is intentionally OCRed once as a complete name.
        # The output contract stores middle name separately, so do not leak
        # subsequent tokens into patient_first.
        return selected.split()[0] if selected.split() else ""
    return selected


def normalize_atomic(field_name: str, raw: str) -> str:
    value = re.sub(r"\s+", " ", raw).strip()
    if field_name == "patient_last":
        return _person_part(value, first=False)
    if field_name == "patient_first":
        return _person_part(value, first=True)
    if field_name == "rel_code":
        upper = value.upper()
        for code, label in (("01", "SELF"), ("02", "SPOUSE"), ("03", "CHILD"), ("04", "OTHER")):
            if re.search(fr"{label}.{{0,8}}X|X.{{0,8}}{label}", upper):
                return code
        return ""
    if field_name.endswith("_state"):
        tokens = re.findall(r"\b[A-Z]{2}\b", value.upper())
        return next((token for token in tokens if token in STATES), "")
    if field_name.endswith("_zip"):
        digits = re.sub(r"\D", "", value)
        return digits if len(digits) in {5, 9} else ""
    if field_name in {"federal_tax_id", "provider_npi", "patient_control_number", "patient_dob"}:
        lengths = {
            "federal_tax_id": 9,
            "provider_npi": 10,
            "patient_control_number": 12,
            "patient_dob": 8,
        }
        groups = re.findall(r"\d+", value)
        digits = "".join(groups)
        length = lengths[field_name]
        candidates = [group for group in groups if len(group) == length]
        return candidates[0] if candidates else (digits if len(digits) == length else "")
    if field_name == "type_of_bill":
        digits = re.sub(r"\D", "", value)
        return digits[-3:] if len(digits) in {3, 4} else ""
    if field_name == "principal_diagnosis":
        match = re.search(r"\b([A-Z]\d{2,6}(?:\.\d+)?)\b", value.upper())
        return re.sub(r"[^A-Z0-9]", "", match.group(1)) if match else ""
    if field_name == "patient_sex":
        match = re.search(r"\b([MF])\b", value.upper())
        return match.group(1) if match else ""
    return re.sub(r"\s+", " ", value).strip(" ,").upper()


def _valid(field_name: str, value: str) -> bool:
    if not value:
        return False
    if field_name.endswith("_state"):
        return value in STATES
    if field_name.endswith("_zip"):
        return len(value) in {5, 9}
    lengths = {
        "federal_tax_id": 9,
        "provider_npi": 10,
        "patient_control_number": 12,
        "patient_dob": 8,
    }
    if field_name in lengths:
        syntax_ok = value.isdigit() and len(value) == lengths[field_name]
        return is_valid_npi(value) if field_name == "provider_npi" and syntax_ok else syntax_ok
    if field_name == "type_of_bill":
        return value.isdigit() and len(value) == 3
    if field_name == "principal_diagnosis":
        return bool(re.fullmatch(r"[A-Z]\d{2,6}", value))
    if field_name == "rel_code":
        return value in {"01", "02", "03", "04"}
    if field_name in {"patient_first", "patient_last"}:
        return bool(re.fullmatch(r"[A-Z][A-Z' -]+", value)) and len(
            re.sub(r"[^A-Z]", "", value)
        ) >= 2
    return len(value) <= 80


def _paddle_lines(
    extractor: PaddleOCRTextExtractor, image: Image.Image, cache: Path
) -> list[TextLine]:
    if cache.is_file():
        return [TextLine(**item) for item in json.loads(cache.read_text(encoding="utf-8"))]
    lines = extractor.extract(image)
    cache.write_text(json.dumps([line.__dict__ for line in lines]), encoding="utf-8")
    return lines


def _relationship_from_pixels(image: Image.Image) -> str:
    gray = image.convert("L")
    # Interior rectangles exclude the printed checkbox borders. Coordinates
    # are relative to the atomic CMS box-6 crop.
    interiors = {
        "01": (68, 18, 88, 39),
        "02": (168, 18, 189, 39),
        "03": (245, 18, 266, 39),
        "04": (343, 18, 364, 39),
    }
    darkness = {}
    for code, box in interiors.items():
        crop = gray.crop(box)
        darkness[code] = sum(pixel < 128 for pixel in crop.getdata()) / (crop.width * crop.height)
    code, score = max(darkness.items(), key=lambda item: item[1])
    return code if score >= 0.06 else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops", type=Path, default=Path("evaluation_results/field_crops"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    parser.add_argument(
        "--prior-predictions", type=Path, default=Path("evaluation_data/predictions.json")
    )
    parser.add_argument("--output", type=Path, default=Path("evaluation_data/predictions_atomic.json"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    prior = PredictionDataset.model_validate_json(
        args.prior_predictions.read_text(encoding="utf-8")
    )
    prior_by_id = {document.document_id: document for document in prior.documents}
    paddle = PaddleOCRTextExtractor()
    cascade = CascadingOCR(
        paddle, [TesseractTextExtractor(psm=6), TesseractTextExtractor(psm=11)]
    )
    documents = []
    for document_id, metadata in sorted(manifest.items()):
        if metadata["form_type"] == "UNSTRUCTURED":
            documents.append(prior_by_id[document_id])
            continue
        fields = []
        for crop_path in sorted((args.crops / document_id).glob("*.png")):
            field_name = crop_path.stem
            with Image.open(crop_path) as source:
                image = source.convert("RGB")
            image_hash = hashlib.sha256(image.tobytes()).hexdigest()[:12]
            primary = _paddle_lines(
                paddle, image, crop_path.with_suffix(f".{image_hash}.paddle.json")
            )
            passes = cascade.extract_candidates(
                image,
                primary_lines=primary,
                cache_prefix=crop_path.with_suffix(f".{image_hash}.cascade"),
            )
            candidates = []
            engine_agreement: dict[str, set[str]] = {}
            for candidate_pass in passes:
                raw, confidence = _joined(candidate_pass.lines)
                value = normalize_atomic(field_name, raw)
                engine_agreement.setdefault(value, set()).add(candidate_pass.engine)
                candidates.append((value, raw, confidence, candidate_pass))
            scored = [
                (
                    confidence
                    + 0.10 * (len(engine_agreement[value]) - 1)
                    + (0.12 if candidate_pass.engine == "paddleocr" else 0),
                    value,
                    raw,
                    confidence,
                    candidate_pass,
                )
                for value, raw, confidence, candidate_pass in candidates
                if _valid(field_name, value)
            ]
            _, value, raw, confidence, winner = max(
                scored,
                key=lambda item: item[0],
                default=(0, "", "", 0.0, passes[0]),
            )
            if field_name == "rel_code":
                pixel_value = _relationship_from_pixels(image)
                if pixel_value:
                    value, raw, confidence = pixel_value, pixel_value, 1.0
            fields.append(
                PredictedField(
                    field_name=field_name,
                    raw_value=value,
                    confidence=confidence,
                    validation_result="VALID" if value else "NEEDS_REVIEW",
                    extraction_method=f"{winner.engine}:{winner.preprocessing}",
                    crop_reference=str(crop_path.relative_to(args.crops.parent)).replace("\\", "/"),
                    accepted=bool(value) and confidence >= 0.90,
                    metadata={
                        "ocr_candidates": [
                            {
                                "engine": candidate_pass.engine,
                                "preprocessing": candidate_pass.preprocessing,
                                "raw": candidate_raw,
                                "value": candidate_value,
                                "confidence": candidate_confidence,
                                "selected": candidate_pass is winner and candidate_value == value,
                            }
                            for candidate_value, candidate_raw, candidate_confidence, candidate_pass
                            in candidates
                        ]
                    },
                )
            )
        by_name = {field.field_name: field for field in fields}
        relationship = by_name.get("rel_code")
        if relationship and relationship.raw_value == "01":
            for field_name in (
                "patient_addr1", "patient_addr2", "patient_city", "patient_state", "patient_zip"
            ):
                if field_name in by_name:
                    by_name[field_name] = by_name[field_name].model_copy(
                        update={"raw_value": "", "normalized_value": None}
                    )
        if by_name.get("insured_addr1") and by_name["insured_addr1"].raw_value == "SAME":
            placeholders = {
                "insured_city": "NA",
                "insured_state": "NA",
                "insured_zip": "999999999",
            }
            for field_name, placeholder in placeholders.items():
                if field_name in by_name:
                    by_name[field_name] = by_name[field_name].model_copy(
                        update={"raw_value": placeholder, "normalized_value": None}
                    )
        documents.append(PredictionDocument(document_id=document_id, fields=list(by_name.values())))
        print(f"Atomic OCR {document_id}: {len(fields)} fields")
    result = PredictionDataset(documents=documents)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
