"""Offline OCR benchmark for the supplied claim-image dataset.

Inference reads image pixels and template geometry only. It deliberately
does not read keyed output files or ground-truth values.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image

from evaluation.schemas import PredictedField, PredictionDataset, PredictionDocument
from workers.cascade.cascading_ocr import CascadingOCR, OCRCandidatePass
from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.page_detection.template_alignment import align_to_reference
from workers.page_detection.text_extraction import PaddleOCRTextExtractor, TextLine


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,")


def _tokens(lines: list[TextLine], x0: float, y0: float, x1: float, y1: float) -> list[TextLine]:
    return sorted(
        [
            line
            for line in lines
            if x0 <= (line.x0 + line.x1) / 2 <= x1
            and y0 <= (line.y0 + line.y1) / 2 <= y1
        ],
        key=lambda line: (line.y0, line.x0),
    )


def _value(lines: list[TextLine], box: tuple[float, float, float, float]) -> tuple[str, float]:
    selected = _tokens(lines, *box)
    return (
        _clean(" ".join(line.text for line in selected)),
        sum(line.confidence for line in selected) / len(selected) if selected else 0.0,
    )


def _cms_parse(lines: list[TextLine]) -> dict[str, tuple[str, float]]:
    patient_name, name_conf = _value(lines, (45, 35, 610, 74))
    insured_name, insured_name_conf = _value(lines, (1025, 35, 1625, 74))
    patient_parts = [_clean(part) for part in patient_name.split(",", 1)]
    if len(patient_parts) == 1:
        patient_parts = patient_name.split(maxsplit=1)
    insured_parts = [_clean(part) for part in insured_name.split(",", 1)]
    if len(insured_parts) == 1:
        insured_parts = insured_name.split(maxsplit=1)

    relation_text, relation_conf = _value(lines, (630, 95, 1005, 137))
    relation_upper = relation_text.upper()
    if re.search(r"SELF\s*X|X\s*SELF|SEL[FT].*X", relation_upper):
        relation = "01"
    elif re.search(r"SPOUSE\s*X|X\s*SPOUSE", relation_upper):
        relation = "02"
    elif re.search(r"CH[IL]+D\s*X|X\s*CH[IL]+D", relation_upper):
        relation = "03"
    else:
        relation = "04" if "OTHER" in relation_upper and "X" in relation_upper else ""

    patient_address, patient_address_conf = _value(lines, (50, 100, 625, 139))
    patient_city, patient_city_conf = _value(lines, (50, 164, 550, 202))
    patient_state, patient_state_conf = _value(lines, (550, 164, 630, 202))
    patient_zip, patient_zip_conf = _value(lines, (50, 222, 320, 260))
    insured_address, insured_address_conf = _value(lines, (1025, 100, 1625, 139))
    insured_city, insured_city_conf = _value(lines, (1025, 164, 1495, 202))
    insured_state, insured_state_conf = _value(lines, (1495, 164, 1625, 202))
    insured_zip, insured_zip_conf = _value(lines, (1025, 222, 1280, 260))

    # CMS semantics: for self, the keyed output intentionally leaves patient
    # address blank and carries the shared address in the insured fields.
    if relation == "01":
        patient_address = patient_city = patient_state = patient_zip = ""
        patient_address_conf = patient_city_conf = patient_state_conf = patient_zip_conf = relation_conf

    def part(parts: list[str], index: int) -> str:
        return parts[index].upper() if len(parts) > index else ""

    return {
        "patient_last": (part(patient_parts, 0), name_conf),
        "patient_first": (part(patient_parts, 1), name_conf),
        "patient_addr1": (patient_address.upper(), patient_address_conf),
        "patient_addr2": ("", patient_address_conf),
        "patient_city": (patient_city.upper(), patient_city_conf),
        "patient_state": (re.sub(r"[^A-Z]", "", patient_state.upper()), patient_state_conf),
        "patient_zip": (re.sub(r"\D", "", patient_zip), patient_zip_conf),
        "rel_code": (relation, relation_conf),
        "insured_addr1": (insured_address.upper(), insured_address_conf),
        "insured_addr2": ("", insured_address_conf),
        "insured_city": (insured_city.upper(), insured_city_conf),
        "insured_state": (re.sub(r"[^A-Z]", "", insured_state.upper()), insured_state_conf),
        "insured_zip": (re.sub(r"\D", "", insured_zip), insured_zip_conf),
    }


def _best_matching(
    lines: list[TextLine],
    box: tuple[float, float, float, float],
    pattern: str,
    lengths: set[int] | None = None,
) -> tuple[str, float]:
    candidates = []
    for line in _tokens(lines, *box):
        for match in re.findall(pattern, line.text.upper()):
            value = re.sub(r"[^A-Z0-9]", "", match)
            if not lengths or len(value) in lengths:
                candidates.append((value, line.confidence))
    return max(candidates, key=lambda item: (item[1], len(item[0])), default=("", 0.0))


def _ub_parse(lines: list[TextLine]) -> dict[str, tuple[str, float]]:
    # These boxes were calibrated against the supplied UB-04 revision after
    # OpenCV homography alignment to the local 1711x2216 reference.
    patient_name_lines = [
        line
        for line in _tokens(lines, 20, 145, 630, 215)
        if "PATIENT" not in line.text.upper() and "ADDRESS" not in line.text.upper()
    ]
    patient_name = max(patient_name_lines, key=lambda line: line.confidence, default=None)
    name_text = _clean(patient_name.text if patient_name else "")
    name_parts = [_clean(part) for part in name_text.split(",", 1)]
    if len(name_parts) == 1:
        name_parts = name_text.split(maxsplit=1)
    name_conf = patient_name.confidence if patient_name else 0.0

    parsed = {
        "federal_tax_id": _best_matching(lines, (950, 100, 1250, 175), r"\d[\d\s-]{7,12}\d", {9}),
        "patient_control_number": _best_matching(
            lines, (950, 10, 1550, 105), r"\d[\d\s-]{9,18}\d", {12}
        ),
        "type_of_bill": _best_matching(lines, (1500, 5, 1711, 115), r"\d{3,4}", {3, 4}),
        "patient_last": ((name_parts[0].upper() if name_parts else ""), name_conf),
        "patient_first": ((name_parts[1].upper() if len(name_parts) > 1 else ""), name_conf),
        "patient_dob": _best_matching(lines, (15, 200, 260, 285), r"\d{8}", {8}),
        "patient_sex": _best_matching(lines, (150, 195, 300, 290), r"\b[MF]\b", {1}),
        "principal_diagnosis": _best_matching(
            lines, (15, 1700, 650, 1950), r"\b[A-Z]\d{2,5}\b", {3, 4, 5, 6, 7}
        ),
        "provider_npi": _best_matching(
            lines, (1000, 1250, 1500, 1550), r"\d[\d\s-]{8,13}\d", {10}
        ),
    }
    return parsed


def _load_or_run_ocr(
    extractor: PaddleOCRTextExtractor, image: Image.Image, cache_path: Path
) -> list[TextLine]:
    if cache_path.is_file():
        return [TextLine(**item) for item in json.loads(cache_path.read_text(encoding="utf-8"))]
    lines = extractor.extract(image.convert("RGB"))
    cache_path.write_text(
        json.dumps([line.__dict__ for line in lines], indent=2), encoding="utf-8"
    )
    return lines


def _prediction(name: str, value: str, confidence: float, crop: str) -> PredictedField:
    accepted = bool(value) and confidence >= 0.90
    return PredictedField(
        field_name=name,
        raw_value=value,
        confidence=confidence,
        validation_result="VALID" if accepted else "NEEDS_REVIEW",
        extraction_method="OPENCV_ALIGNED_PADDLEOCR",
        crop_reference=crop,
        accepted=accepted,
        reviewed=False,
    )


def _valid_candidate(field_name: str, value: str) -> bool:
    if not value:
        return True
    if field_name in {"patient_last", "patient_first", "patient_city", "insured_city"}:
        return bool(re.fullmatch(r"[A-Z][A-Z .'-]{1,39}", value))
    if field_name.endswith("_state"):
        return bool(re.fullmatch(r"[A-Z]{2}|NA", value))
    if field_name.endswith("_zip"):
        return bool(re.fullmatch(r"\d{5}(?:\d{4})?|999999999", value))
    if field_name == "rel_code":
        return value in {"01", "02", "03", "04", "09"}
    if field_name == "federal_tax_id":
        return bool(re.fullmatch(r"\d{9}", value))
    if field_name == "provider_npi":
        return bool(re.fullmatch(r"\d{10}", value))
    if field_name == "patient_dob":
        return bool(re.fullmatch(r"\d{8}", value))
    if field_name == "type_of_bill":
        return bool(re.fullmatch(r"\d{3,4}", value))
    if field_name == "principal_diagnosis":
        return bool(re.fullmatch(r"[A-Z]\d{2,6}", value))
    return len(value) <= 80


def _ensemble_parse(
    passes: list[OCRCandidatePass], parser
) -> tuple[dict[str, tuple[str, float]], dict[str, list[dict[str, object]]]]:
    parsed_passes = [
        (candidate_pass, parser(candidate_pass.lines)) for candidate_pass in passes
    ]
    selected: dict[str, tuple[str, float]] = {}
    diagnostics: dict[str, list[dict[str, object]]] = {}
    field_names = set().union(*(values.keys() for _, values in parsed_passes))
    for field_name in field_names:
        candidates = []
        agreement: dict[str, set[str]] = {}
        for candidate_pass, values in parsed_passes:
            value, confidence = values.get(field_name, ("", 0.0))
            value = _clean(value).upper()
            agreement.setdefault(value, set()).add(candidate_pass.engine)
            candidates.append((value, confidence, candidate_pass))
        scored = [
            (
                confidence
                + min(0.16, 0.08 * (len(agreement[value]) - 1))
                + (0.25 if candidate_pass.engine == "paddleocr" else 0.0),
                value,
                confidence,
                candidate_pass,
            )
            for value, confidence, candidate_pass in candidates
            if _valid_candidate(field_name, value)
        ]
        _, value, confidence, winner = max(
            scored,
            key=lambda item: (item[0], bool(item[1]), item[2]),
            default=(0.0, "", 0.0, passes[0]),
        )
        selected[field_name] = (value, confidence)
        diagnostics[field_name] = [
            {
                "engine": candidate_pass.engine,
                "preprocessing": candidate_pass.preprocessing,
                "value": candidate_value,
                "confidence": candidate_confidence,
                "selected": candidate_pass is winner and candidate_value == value,
            }
            for candidate_value, candidate_confidence, candidate_pass in candidates
        ]
    return selected, diagnostics


def _unstructured_parse(lines: list[TextLine]) -> dict[str, tuple[str, float]]:
    name_line = next(
        (
            line
            for line in lines
            if re.search(r"\b(CLIENT|PATIENT)\s*NAME\b", line.text.upper())
        ),
        None,
    )
    name = ""
    confidence = 0.0
    if name_line:
        name = re.sub(
            r"^.*?\b(?:CLIENT|PATIENT)\s*NAME\s*:?", "", name_line.text, flags=re.I
        ).strip()
        confidence = name_line.confidence
        if not name:
            nearby = [
                line
                for line in lines
                if line.x0 >= name_line.x0
                and name_line.y0 - 15 <= line.y0 <= name_line.y1 + 55
                and line is not name_line
            ]
            if nearby:
                candidate = min(nearby, key=lambda line: abs(line.y0 - name_line.y0))
                name, confidence = candidate.text, candidate.confidence
    parts = [_clean(part) for part in re.split(r",|\s+", name) if _clean(part)]
    patient_last = parts[0].upper() if parts else ""
    patient_first = parts[1].upper() if len(parts) > 1 else ""
    empty = ("", 0.0)
    return {
        "patient_last": (patient_last, confidence),
        "patient_first": (patient_first, confidence),
        "patient_addr1": empty,
        "patient_addr2": empty,
        "patient_city": empty,
        "patient_state": empty,
        "patient_zip": empty,
        "rel_code": ("09", confidence),
        "insured_addr1": empty,
        "insured_addr2": empty,
        "insured_city": empty,
        "insured_state": empty,
        "insured_zip": empty,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_data/predictions.json"))
    parser.add_argument("--assets", type=Path, default=Path("evaluation_results/assets"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    args = parser.parse_args()
    args.assets.mkdir(parents=True, exist_ok=True)
    extractor = PaddleOCRTextExtractor()
    cascade = CascadingOCR(
        extractor,
        [TesseractTextExtractor(psm=6), TesseractTextExtractor(psm=11)],
    )
    documents: list[PredictionDocument] = []

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cms_reference_path = Path("config/templates/reference_images/cms1500_v02_12.png")
    with Image.open(cms_reference_path) as reference_source:
        cms_reference = reference_source.convert("L")

    for document_id, metadata in sorted(manifest.items()):
        if metadata["form_type"] == "UB04":
            continue
        source = args.dataset / str(metadata["file_name"])
        with Image.open(source) as image:
            image.seek(int(metadata["page_number"]) - 1)
            selected_page = image.convert("L")
        alignment = align_to_reference(selected_page, cms_reference)
        is_cms = metadata["form_type"] == "CMS1500" and alignment.success
        evidence = alignment.warped if is_cms and alignment.warped is not None else selected_page
        preview_path = args.assets / f"{document_id}.png"
        evidence.save(preview_path, "PNG", optimize=True)
        if is_cms:
            # Include the complete ZIP row; the historical strip ended at
            # y=545 and visibly clipped the values.
            ocr_image = evidence.crop((0, 300, evidence.width, 610))
            cache_path = args.assets / f"{document_id}.source-v2.ocr.json"
            lines = _load_or_run_ocr(extractor, ocr_image, cache_path)
            passes = cascade.extract_candidates(
                ocr_image,
                primary_lines=lines,
                cache_prefix=args.assets / f"{document_id}.cascade",
            )
            parsed, candidate_metadata = _ensemble_parse(passes, _cms_parse)
        else:
            cache_path = args.assets / f"{document_id}.source-v2.ocr.json"
            # Full unstructured pages are expensive for CPU PaddleOCR and can
            # exhaust Docker Desktop memory when processed at 200-DPI source
            # resolution. Text anchors remain readable at half scale.
            ocr_image = evidence.copy()
            ocr_image.thumbnail((1000, 1400), Image.Resampling.LANCZOS)
            # Some handwritten/noisy Group-D pages trigger pathological
            # Paddle detector runtime. Reuse a completed Paddle cache when
            # present; otherwise escalate directly to Tesseract instead of
            # allowing one page to stall the entire batch.
            lines = (
                [TextLine(**item) for item in json.loads(cache_path.read_text(encoding="utf-8"))]
                if cache_path.is_file()
                else []
            )
            passes = cascade.extract_candidates(
                ocr_image,
                primary_lines=lines,
                cache_prefix=args.assets / f"{document_id}.cascade",
            )
            parsed, candidate_metadata = _ensemble_parse(passes, _unstructured_parse)
        documents.append(
            PredictionDocument(
                document_id=document_id,
                fields=[
                    _prediction(name, value, confidence, f"assets/{preview_path.name}").model_copy(
                        update={"metadata": {"ocr_candidates": candidate_metadata[name]}}
                    )
                    for name, (value, confidence) in parsed.items()
                ],
            )
        )
        print(f"OCR {document_id}")

    reference_path = Path("config/templates/reference_images/ub04_v2014.png")
    with Image.open(reference_path) as reference_source:
        reference = reference_source.convert("L")
    ub_documents = [
        (document_id, metadata)
        for document_id, metadata in sorted(manifest.items())
        if metadata["form_type"] == "UB04"
    ]
    for document_id, metadata in ub_documents:
        source = args.dataset / str(metadata["file_name"])
        with Image.open(source) as image:
            image.seek(int(metadata["page_number"]) - 1)
            alignment = align_to_reference(image.convert("L"), reference)
        if not alignment.success or alignment.warped is None:
            raise RuntimeError(f"OpenCV alignment failed for {source}")
        preview_path = args.assets / f"{document_id}.png"
        alignment.warped.save(preview_path, "PNG", optimize=True)
        lines = _load_or_run_ocr(
            extractor, alignment.warped, args.assets / f"{document_id}.ocr.json"
        )
        passes = cascade.extract_candidates(
            alignment.warped,
            primary_lines=lines,
            cache_prefix=args.assets / f"{document_id}.cascade",
        )
        parsed, candidate_metadata = _ensemble_parse(passes, _ub_parse)
        documents.append(
            PredictionDocument(
                document_id=document_id,
                fields=[
                    _prediction(name, value, confidence, f"assets/{preview_path.name}").model_copy(
                        update={"metadata": {"ocr_candidates": candidate_metadata[name]}}
                    )
                    for name, (value, confidence) in parsed.items()
                ],
            )
        )
        print(f"OCR {document_id}")

    predictions = PredictionDataset(documents=sorted(documents, key=lambda item: item.document_id))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(predictions.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {len(documents)} prediction documents to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
