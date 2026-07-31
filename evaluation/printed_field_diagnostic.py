"""Twenty-field printed-form diagnostic with visual and token-level evidence."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset
from packages.templates.registry import TemplateRegistry
from workers.field_candidates.parsers import parse_alternatives
from workers.retry.alternate_preprocessing import (
    adaptive_threshold,
    aggressive_contrast,
    remove_printed_lines,
    upscale,
)

TARGET_CASES = (
    *( (document_id, "patient_zip") for document_id in ("A-04", "A-08", "A-10", "A-11") ),
    *((f"C-{index:02d}", field_name) for index in range(1, 5) for field_name in (
        "provider_npi", "patient_dob", "type_of_bill", "principal_diagnosis",
    )),
)


def _ink_ratio(image: Image.Image) -> float:
    gray = np.array(image.convert("L"))
    return float(np.count_nonzero(gray < 235) / gray.size)


def _load_tokens(crop_root: Path, field_name: str) -> dict[str, list[dict]]:
    sources = {"paddle_original": crop_root / f"{field_name}.paddle.json"}
    for engine in ("tesseract_psm_6", "tesseract_psm_11"):
        for variant in ("original", "aggressive_contrast", "binarize_sharpen"):
            sources[f"{engine}_{variant}"] = crop_root / f"{field_name}.cascade.{engine}.{variant}.json"
    return {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in sources.items() if path.is_file()
    }


def _candidate_rows(tokens_by_provider: dict[str, list[dict]], field_name: str) -> list[dict]:
    rows = []
    for provider, tokens in tokens_by_provider.items():
        raw_values = [token.get("text", "") for token in tokens if token.get("text")]
        alternatives = []
        for raw in raw_values + ([" ".join(raw_values)] if len(raw_values) > 1 else []):
            alternatives.extend(parse_alternatives(field_name, raw))
        for normalized, validations in alternatives:
            confidences = [
                float(token.get("confidence", 0.0)) for token in tokens
                if token.get("text")
            ]
            engine = (
                "tesseract" if provider.startswith("tesseract")
                else "paddleocr" if provider.startswith("paddle")
                else provider
            )
            preprocessing = (
                provider.removeprefix("tesseract_psm_6_")
                .removeprefix("tesseract_psm_11_")
                .removeprefix("paddle_")
            )
            rows.append({
                "provider": provider,
                "engine": engine,
                "model": provider.split("_")[0],
                "preprocessing_variant": preprocessing,
                "raw": raw_values,
                "normalized": normalized,
                "raw_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
                "calibrated_confidence": None,
                "validation_results": list(validations),
                "selection_reason": "valid_constrained_alternative_retained",
                "regional_provenance": "FIELD_CROP",
                "semantic_reference_status": "REFERENCE_UNAVAILABLE",
            })
    return rows


def _crop_box(region, source: Image.Image, reference_width: int, reference_height: int):
    scale_x, scale_y = source.width / reference_width, source.height / reference_height
    padding = 5
    return (
        max(0, int(region.x0 * scale_x) - padding),
        max(0, int(region.y0 * scale_y) - padding),
        min(source.width, int(region.x1 * scale_x) + padding),
        min(source.height, int(region.y1 * scale_y) + padding),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument("--truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument("--manifest", type=Path, default=Path("evaluation_data/document_manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/printed_diagnostic"))
    args = parser.parse_args()
    truth = GroundTruthDataset.model_validate_json(args.truth.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    truth_docs = {document.document_id: document for document in truth.documents}
    templates = TemplateRegistry.load_from_directory()
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for document_id, field_name in TARGET_CASES:
        document_dir = args.output / document_id
        document_dir.mkdir(exist_ok=True)
        metadata = manifest[document_id]
        template = (
            templates.get("cms1500", "02-12")
            if metadata["form_type"] == "CMS1500"
            else templates.get("ub04", "2014")
        )
        page_number = metadata["page_number"]
        with Image.open(args.dataset / metadata["file_name"]) as source_file:
            source_file.seek(page_number - 1)
            source = source_file.convert("RGB")
        source.save(document_dir / "original_page.png")
        aligned = source.resize(
            (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
        )
        aligned.save(document_dir / "aligned_page_UNAVAILABLE_rescale_only.png")
        region = template.field_region(field_name)
        assert region is not None
        box = _crop_box(
            region, source,
            template.reference_dimensions.width_px,
            template.reference_dimensions.height_px,
        )
        overlay = source.copy()
        draw = ImageDraw.Draw(overlay)
        draw.rectangle(box, outline="red", width=5)
        draw.text((box[0], max(0, box[1] - 18)), field_name, fill="red")
        overlay.save(document_dir / f"{field_name}_overlay.png")
        crop = source.crop(box)
        crop.save(document_dir / f"{field_name}_original.png")
        variants = {
            "upscale_2x": upscale(crop),
            "clahe": aggressive_contrast(crop),
            "adaptive_threshold": adaptive_threshold(crop),
        }
        line_removed, line_safe, ink_loss = remove_printed_lines(crop)
        if line_safe:
            variants["line_removed"] = line_removed
        for name, image in variants.items():
            image.save(document_dir / f"{field_name}_{name}.png")
        tokens = _load_tokens(
            Path("evaluation_results/field_crops") / document_id, field_name
        )
        candidates = _candidate_rows(tokens, field_name)
        truth_field = next(
            field for field in truth_docs[document_id].fields
            if field.field_name == field_name
        )
        expected_raw = truth_field.expected_normalized or truth_field.expected_raw
        expected = normalizers.normalize(field_name, expected_raw)
        matches = [
            candidate for candidate in candidates
            if normalizers.normalize(field_name, candidate["normalized"]) == expected
        ]
        ink_ratio = _ink_ratio(crop)
        valid_crop = crop.width > 0 and crop.height > 0 and ink_ratio >= 0.001
        expected_blank = expected is None
        if expected_blank:
            outcome = (
                "EXPECTED_BLANK_FALSE_POSITIVE"
                if any(candidate["normalized"] for candidate in candidates)
                else "EXPECTED_BLANK_CORRECT"
            )
        elif matches:
            outcome = "MATCH"
        else:
            outcome = "REQUIRED_FIELD_MISSING"
        ocr_responded = any(tokens.values())
        raw_compact = {
            re.sub(r"[^A-Z0-9]", "", token.get("text", "").upper())
            for provider_tokens in tokens.values() for token in provider_tokens
        }
        expected_compact = re.sub(r"[^A-Z0-9]", "", (expected or "").upper())
        if not valid_crop:
            likely_cause = "ALIGNMENT_OR_COORDINATE_PROBLEM"
        elif not ocr_responded:
            likely_cause = "OCR_OR_PREPROCESSING_PROBLEM"
        elif expected_compact in raw_compact and not matches:
            likely_cause = "PARSER_PROBLEM"
        elif not matches:
            likely_cause = "OCR_CANDIDATE_GENERATION_PROBLEM"
        else:
            likely_cause = "PASS"
        record = {
                "document_id": document_id,
                "field_name": field_name,
                "family": metadata["form_type"],
                "page_number": page_number,
                "coordinate_frame": "REFERENCE_TEMPLATE_TO_SOURCE_PAGE_RESCALE_ONLY",
                "alignment_status": "UNAVAILABLE_NO_APPROVED_BLANK_REFERENCE",
                "alignment_score": 0.0,
                "source_page_box": box,
                "crop_valid": valid_crop,
                "ink_ratio": ink_ratio,
                "line_removal_safe": line_safe,
                "line_removal_ink_loss": ink_loss,
                "tokens": tokens,
                "raw_candidates": [
                    {"provider": candidate["provider"], "raw": candidate["raw"]}
                    for candidate in candidates
                ],
                "normalized_candidates": candidates,
                "expected_evaluation_value": expected_raw,
                "coverage_match": bool(matches),
                "matching_providers": sorted({
                    candidate["provider"] for candidate in matches
                }),
                "outcome": outcome,
                "likely_cause": likely_cause,
                "candidate_selection_reasons": [
                    candidate["selection_reason"] for candidate in candidates
                ] or ["no_valid_parser_output"],
        }
        (document_dir / f"{field_name}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        rows.append(record)
    metrics = _metrics(rows)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.output / "diagnostic.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (args.output / "report.html").write_text(_html(rows, metrics), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


def _metrics(rows: list[dict]) -> dict:
    count = len(rows)
    by_provider = defaultdict(lambda: [0, 0])
    by_field = defaultdict(lambda: [0, 0])
    by_family = defaultdict(lambda: [0, 0])
    for row in rows:
        by_field[row["field_name"]][1] += 1
        by_field[row["field_name"]][0] += row["coverage_match"]
        by_family[row["family"]][1] += 1
        by_family[row["family"]][0] += row["coverage_match"]
        providers = set(row["tokens"])
        matching = set(row["matching_providers"])
        for provider in providers:
            by_provider[provider][1] += 1
            by_provider[provider][0] += provider in matching
    ratio = lambda predicate: sum(predicate(row) for row in rows) / count
    return {
        "fields": count,
        "crop_validity_rate": ratio(lambda row: row["crop_valid"]),
        "nonblank_crop_rate": ratio(lambda row: row["ink_ratio"] >= 0.001),
        "ocr_response_rate": ratio(lambda row: any(row["tokens"].values())),
        "parser_yield_rate": ratio(lambda row: bool(row["normalized_candidates"])),
        "hard_validation_pass_rate": ratio(lambda row: bool(row["normalized_candidates"])),
        "candidate_coverage": ratio(lambda row: row["coverage_match"]),
        "outcomes": {
            name: sum(row["outcome"] == name for row in rows)
            for name in (
                "MATCH", "EXPECTED_BLANK_CORRECT",
                "EXPECTED_BLANK_FALSE_POSITIVE", "REQUIRED_FIELD_MISSING",
            )
        },
        "candidate_coverage_by_provider": {
            key: passed / total for key, (passed, total) in by_provider.items()
        },
        "candidate_coverage_by_field": {
            key: passed / total for key, (passed, total) in by_field.items()
        },
        "candidate_coverage_by_family": {
            key: passed / total for key, (passed, total) in by_family.items()
        },
    }


def _html(rows: list[dict], metrics: dict) -> str:
    cards = []
    for row in rows:
        root = row["document_id"]
        candidates = "<br>".join(
            html.escape(f"{item['provider']}: {item['normalized']}")
            for item in row["normalized_candidates"]
        ) or "NO VALID CANDIDATE"
        cards.append(f"""
<section><h2>{html.escape(row['document_id'])} — {html.escape(row['field_name'])}</h2>
<div class="grid">
<figure><img src="{root}/original_page.png"><figcaption>Original page</figcaption></figure>
<figure><img src="{root}/{row['field_name']}_overlay.png"><figcaption>Source-page overlay</figcaption></figure>
<figure><img src="{root}/{row['field_name']}_original.png"><figcaption>Original crop</figcaption></figure>
<figure><img src="{root}/{row['field_name']}_adaptive_threshold.png"><figcaption>Adaptive threshold</figcaption></figure>
</div><p><b>Expected:</b> {html.escape(str(row['expected_evaluation_value']))}<br>
<b>Candidates:</b><br>{candidates}<br><b>Outcome:</b> {row['outcome']}<br>
<b>Alignment:</b> {row['alignment_status']}</p></section>""")
    return f"""<!doctype html><meta charset="utf-8"><title>Printed field diagnostic</title>
<style>body{{font-family:system-ui;margin:20px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
img{{max-width:100%;max-height:360px;border:1px solid #999}}section{{border-top:2px solid #333;margin:24px 0}}
pre{{background:#eee;padding:12px}}</style><h1>Evaluation-only 20-field diagnostic</h1>
<pre>{html.escape(json.dumps(metrics, indent=2))}</pre>{''.join(cards)}"""


if __name__ == "__main__":
    raise SystemExit(main())
