"""Docker-free printed OCR for recurring D-04–D-07 document families."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from PIL import Image

from evaluation.schemas import PredictionDataset
from workers.standard_form_extraction.structured_fields import parse_person_name
from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter, TrOCRResult


def _crop(image: Image.Image, box: list[float]) -> Image.Image:
    return image.crop((
        int(box[0] * image.width), int(box[1] * image.height),
        int(box[2] * image.width), int(box[3] * image.height),
    ))


def _score(text: str, phrases: list[str]) -> float:
    normalized = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return max(
        (
            1.0 if phrase in normalized
            else SequenceMatcher(None, phrase, normalized).ratio()
            for phrase in phrases
        ),
        default=0.0,
    )


def _region_key(box: list[float]) -> str:
    encoded = ",".join(f"{coordinate:.4f}" for coordinate in box).encode()
    return hashlib.sha1(encoded).hexdigest()[:8]


def _normalize_numeric_ocr(value: str) -> str:
    """Repair common glyph confusions only inside a numeric field."""
    return value.upper().translate(str.maketrans({
        "O": "0", "I": "1", "L": "1", "B": "8", "S": "5", "/": "7",
    }))


def _reconcile_po_box_with_zip(address: str, postal_code: str) -> str:
    """Repair an ambiguous PO-box suffix using a visible ZIP+4 extension.

    This is intentionally narrow: it requires a PO BOX label, an OCR-ambiguous
    numeric suffix, and a nine-digit postal code. It never invents a street
    address or uses evaluation/reference data.
    """
    match = re.fullmatch(r"\s*PO\s+BOX\s+([0-9OBISL/]+)\s*", address.upper())
    postal_digits = re.sub(r"\D", "", postal_code)
    if not match or len(postal_digits) != 9:
        return address
    suffix = match.group(1)
    if not re.search(r"[OBISL/]", suffix):
        return address
    unambiguous_prefix = re.match(r"\d+", suffix)
    if not unambiguous_prefix:
        return address
    prefix = unambiguous_prefix.group()
    extension = postal_digits[-4:]
    overlap = max(
        (
            size for size in range(1, min(len(prefix), len(extension)) + 1)
            if prefix[-size:] == extension[:size]
        ),
        default=0,
    )
    box_number = prefix + extension[overlap:]
    return f"PO BOX {box_number}"


def _recognize_cached_batch(
    adapter: TrOCRAdapter,
    requests: list[tuple[Image.Image, Path]],
    batch_size: int = 8,
) -> list[TrOCRResult]:
    """Resolve cached OCR and infer cache misses in bounded batches."""
    results: list[TrOCRResult | None] = [None] * len(requests)
    misses: list[tuple[int, Image.Image, Path]] = []
    for index, (image, cache) in enumerate(requests):
        if cache.is_file():
            results[index] = TrOCRResult(**json.loads(cache.read_text(encoding="utf-8")))
        else:
            misses.append((index, image, cache))
    for offset in range(0, len(misses), batch_size):
        batch = misses[offset:offset + batch_size]
        inferred = adapter.recognize_batch([item[1] for item in batch])
        for (index, _image, cache), result in zip(batch, inferred, strict=True):
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(result.__dict__), encoding="utf-8")
            results[index] = result
    return [result for result in results if result is not None]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--predictions", type=Path,
        default=Path("evaluation_data/predictions_family_cascade.json"),
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument(
        "--config", type=Path, default=Path("config/unstructured_fixed_regions.yaml")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation_data/predictions_fixed_family.json")
    )
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    predictions = PredictionDataset.model_validate_json(
        args.predictions.read_text(encoding="utf-8")
    )
    documents = {document.document_id: document for document in predictions.documents}
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    families = yaml.safe_load(args.config.read_text(encoding="utf-8"))["families"]
    adapter = TrOCRAdapter("microsoft/trocr-base-printed", min_confidence=0.0)
    cache_root = Path("evaluation_results/fixed_family_ocr")

    for document_id, metadata in manifest.items():
        if metadata["form_type"] != "UNSTRUCTURED" or document_id in {"D-01", "D-02", "D-03"}:
            continue
        source_path = args.dataset / metadata["file_name"]
        page_candidates: list[tuple[float, str, int, Image.Image, str]] = []
        pages: list[tuple[int, Image.Image]] = []
        with Image.open(source_path) as source:
            for page_index in range(getattr(source, "n_frames", 1)):
                source.seek(page_index)
                pages.append((page_index + 1, source.convert("RGB")))
        title_keys: list[tuple[str, int, Image.Image]] = []
        title_requests: list[tuple[Image.Image, Path]] = []
        for page_number, page in pages:
            for family, spec in families.items():
                for band_index, band in enumerate(spec["title_bands"]):
                    title_keys.append((family, page_number, page))
                    title_requests.append((
                        _crop(page, band),
                        cache_root / (
                            f"{document_id}.p{page_number}.{family}.title{band_index}.json"
                        ),
                    ))
        title_results = _recognize_cached_batch(
            adapter, title_requests, batch_size=args.batch_size
        )
        grouped_titles: dict[tuple[str, int], list[str]] = {}
        grouped_pages: dict[tuple[str, int], Image.Image] = {}
        for (family, page_number, page), result in zip(
            title_keys, title_results, strict=True
        ):
            grouped_titles.setdefault((family, page_number), []).append(result.text or "")
            grouped_pages[(family, page_number)] = page
        for (family, page_number), band_texts in grouped_titles.items():
            title_text = " ".join(band_texts)
            page_candidates.append((
                _score(title_text, families[family]["title_phrases"]),
                family, page_number, grouped_pages[(family, page_number)], title_text,
            ))
        score, family, page_number, page, title_text = max(
            page_candidates, key=lambda item: item[0]
        )
        if score < 0.30:
            print(document_id, "no confident family", f"{score:.2f}", title_text)
            continue
        spec = families[family]
        raw: dict[str, tuple[str, float, str]] = {}
        crop_dir = Path("evaluation_results/field_crops") / document_id
        crop_dir.mkdir(parents=True, exist_ok=True)
        field_names: list[str] = []
        field_boxes: list[list[float]] = []
        field_requests: list[tuple[Image.Image, Path]] = []
        for field_name, box in spec["fields"].items():
            field_crop = _crop(page, box)
            field_crop.save(crop_dir / f"{field_name}_fixed.png", "PNG")
            field_names.append(field_name)
            field_boxes.append(box)
            field_requests.append((
                field_crop,
                cache_root / (
                    f"{document_id}.p{page_number}.{family}.{field_name}."
                    f"{_region_key(box)}.json"
                ),
            ))
        field_results = _recognize_cached_batch(
            adapter, field_requests, batch_size=args.batch_size
        )
        for field_name, box, result in zip(
            field_names, field_boxes, field_results, strict=True
        ):
            raw[field_name] = (result.text or "", result.confidence, str(box))
        values: dict[str, tuple[str, float, str]] = {}
        derived_evidence: dict[str, dict[str, object]] = {}
        if "patient_name" in raw:
            text, confidence, box = raw["patient_name"]
            parsed = parse_person_name(text, "FIRST_MIDDLE_LAST")
            values["patient_first"] = (parsed.first.upper(), confidence, box)
            values["patient_last"] = (parsed.last.upper(), confidence, box)
        for name in ("patient_first", "patient_last", "patient_addr1", "patient_city",
                     "patient_state", "patient_zip"):
            if name in raw:
                text, confidence, box = raw[name]
                value = re.sub(r"\s+", " ", text).strip(" ,.-").upper()
                if name == "patient_zip":
                    value = re.sub(r"\D", "", value)
                values[name] = (value, confidence, box)
        if "patient_city_line" in raw:
            text, confidence, box = raw["patient_city_line"]
            match = re.search(
                r"(?P<city>[A-Za-z ]+),?\s+(?P<state>[A-Z]{2})\s+"
                r"(?P<zip>[0-9OBISL]{5}(?:-[0-9OBISL/]{4})?)",
                text,
            )
            if match:
                normalized_zip = _normalize_numeric_ocr(match.group("zip"))
                values.update({
                    "patient_city": (match.group("city").strip().upper(), confidence, box),
                    "patient_state": (match.group("state"), confidence, box),
                    "patient_zip": (re.sub(r"\D", "", normalized_zip), confidence, box),
                })
        if "patient_addr1" in values and "patient_zip" in values:
            address, confidence, box = values["patient_addr1"]
            repaired = _reconcile_po_box_with_zip(address, values["patient_zip"][0])
            values["patient_addr1"] = (repaired, confidence, box)
            if repaired != address:
                derived_evidence["patient_addr1"] = {
                    "raw_address_evidence": address,
                    "raw_zip_evidence": values["patient_zip"][0],
                    "derived_candidate": repaired,
                    "method": "CROSS_FIELD_PO_BOX_REPAIR",
                    "semantic_state": "DERIVED_UNVERIFIED",
                    "authority": "REVIEW_ONLY",
                    "automatically_acceptable": False,
                    "requires_reference_verification": True,
                    "requires_human_review": True,
                    "reason_codes": [
                        "CROSS_FIELD_REPAIR_UNVERIFIED",
                        "ADDRESS_REFERENCE_REQUIRED",
                        "HUMAN_REVIEW_REQUIRED",
                    ],
                    "reason": "postal_relationship_not_authoritatively_verified",
                }
        fields = {field.field_name: field for field in documents[document_id].fields}
        for field_name, (value, confidence, box) in values.items():
            if not value or field_name not in fields:
                continue
            field = fields[field_name]
            field.raw_value = value
            field.normalized_value = None
            field.confidence = confidence
            field.extraction_method = "TROCR_PRINTED_FIXED_FAMILY"
            field.accepted = False
            field.validation_result = "NEEDS_REVIEW"
            field.fallback_used = True
            if field_name in derived_evidence:
                field.metadata["derived_evidence"] = derived_evidence[field_name]
                field.validation_result = "REVIEW_ONLY_CROSS_FIELD_DERIVATION"
                field.accepted = False
            field.metadata.update({
                "document_family": family,
                "routed_page": page_number,
                "family_confidence": score,
                "normalized_region": box,
                "model_name": adapter.model_name,
                "disposition": "HUMAN_REVIEW_REQUIRED",
                "disposition_reason": (
                    "person_name_requires_authoritative_reference_match"
                    if field_name in {"patient_first", "patient_last"}
                    else "single_engine_candidate_requires_review"
                ),
            })
        print(document_id, family, page_number, f"{score:.2f}", values)
    args.output.write_text(predictions.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
