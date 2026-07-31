"""Run TrOCR only on unresolved handwriting-suitable atomic field crops."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml
from PIL import Image

from evaluation.run_atomic_ocr import _valid, normalize_atomic
from evaluation.schemas import PredictionDataset
from workers.retry.alternate_preprocessing import remove_printed_lines, upscale
from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter, TrOCRResult

HANDWRITING_FIELDS = {
    "patient_last", "patient_first", "patient_addr1", "patient_addr2",
    "patient_city", "insured_addr1", "insured_addr2", "insured_city",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops", type=Path, default=Path("evaluation_results/field_crops"))
    parser.add_argument(
        "--predictions", type=Path, default=Path("evaluation_data/predictions_atomic.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation_data/predictions_handwriting.json")
    )
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    dataset = PredictionDataset.model_validate_json(
        args.predictions.read_text(encoding="utf-8")
    )
    crop_manifest = json.loads((args.crops / "crop_manifest.json").read_text(encoding="utf-8"))
    document_manifest = json.loads(
        Path("evaluation_data/document_manifest.json").read_text(encoding="utf-8")
    )
    field_contract = yaml.safe_load(
        Path("config/evaluation/field_contract.yaml").read_text(encoding="utf-8")
    )
    pending: list[tuple[object, Path, dict]] = []
    for document in dataset.documents:
        by_name = {field.field_name: field for field in document.fields}
        self_relationship = (
            by_name.get("rel_code") is not None
            and by_name["rel_code"].raw_value == "01"
        )
        for field in document.fields:
            key = f"{document.document_id}/{field.field_name}"
            crop = args.crops / document.document_id / f"{field.field_name}.png"
            route = crop_manifest.get(key, {})
            if (
                field.field_name in HANDWRITING_FIELDS
                and not (
                    self_relationship
                    and field.field_name.startswith("patient_addr")
                    or self_relationship
                    and field.field_name == "patient_city"
                )
                and crop.is_file()
                and (not field.accepted or field.validation_result != "VALID")
                and route.get("writing_type") in {"HANDWRITTEN", "MIXED"}
            ):
                pending.append((field, crop, route))

    adapter = TrOCRAdapter(min_confidence=0.0)
    for start in range(0, len(pending), args.batch_size):
        batch = pending[start:start + args.batch_size]
        uncached: list[tuple[object, Path, dict]] = []
        results: dict[Path, TrOCRResult] = {}
        for item in batch:
            cache = item[1].with_suffix(".trocr_lines_v2.json")
            if not cache.is_file():
                # Compatibility with results produced before the cache
                # filename was versioned; those files contain the same v2
                # line-removed preprocessing result.
                legacy_cache = item[1].with_suffix(".trocr.json")
                if legacy_cache.is_file():
                    cache = legacy_cache
            if cache.is_file():
                payload = json.loads(cache.read_text(encoding="utf-8"))
                results[item[1]] = TrOCRResult(**payload)
            else:
                uncached.append(item)
        if uncached:
            images = []
            for _, path, _ in uncached:
                with Image.open(path) as source:
                    original = source.convert("RGB")
                cleaned, _, _ = remove_printed_lines(
                    original, maximum_ink_loss=0.35
                )
                # Remove form-border remnants and give the recognizer enough
                # vertical resolution without changing aspect ratio.
                margin_x = min(3, max(cleaned.width // 30, 0))
                margin_y = min(2, max(cleaned.height // 20, 0))
                cleaned = cleaned.crop(
                    (margin_x, margin_y, cleaned.width - margin_x, cleaned.height - margin_y)
                )
                images.append(upscale(cleaned, 3))
            inferred = adapter.recognize_batch(images)
            for item, result in zip(uncached, inferred, strict=True):
                results[item[1]] = result
                item[1].with_suffix(".trocr_lines_v2.json").write_text(
                    json.dumps(result.__dict__), encoding="utf-8"
                )
        for field, path, route in batch:
            result = results[path]
            raw = result.text or ""
            value = normalize_atomic(field.field_name, raw)
            candidates = list(field.metadata.get("ocr_candidates", []))
            candidates.append({
                "engine": "trocr",
                "model": adapter.model_name,
                "preprocessing": "local_aligned_line_removed_upscale3x",
                "raw": raw,
                "value": value,
                "confidence": result.confidence,
                "selected": False,
            })
            agreement: dict[str, set[str]] = defaultdict(set)
            for candidate in candidates:
                if candidate.get("value"):
                    agreement[str(candidate["value"])].add(str(candidate["engine"]).split("_")[0])
            valid = _valid(field.field_name, value)
            independently_agreed = len(agreement[value]) >= 2 if value else False
            # Handwriting values are never accepted from one OCR confidence
            # alone. Independent agreement or external reference verification
            # is required; the evaluation runner has no production reference
            # database configured, so it enforces agreement.
            accept = valid and independently_agreed
            if accept:
                previous_value = field.raw_value
                candidates[-1]["selected"] = True
                field.raw_value = value
                field.normalized_value = None
                field.confidence = result.confidence
                field.extraction_method = "trocr:local_aligned_line_removed_upscale3x"
                field.validation_result = "VALID"
                field.accepted = True
                field.fallback_used = True
                field.before_fallback_value = (
                    field.before_fallback_value
                    if field.before_fallback_value is not None else previous_value
                )
            field.metadata.update({
                "ocr_candidates": candidates,
                "writing_type": route.get("writing_type"),
                "writing_confidence": route.get("writing_confidence"),
                "alignment_score": route.get("alignment_score"),
                "local_match_score": route.get("local_match_score"),
                "cascade_stage": "TROCR" if accept else "HUMAN_REVIEW",
                "disposition": (
                    "VALIDATED_AUTOMATICALLY" if accept else "HUMAN_REVIEW_REQUIRED"
                ),
            })
        print(f"TrOCR {min(start + len(batch), len(pending))}/{len(pending)}")

    # Apply controlled disposition to every critical field, including values
    # that were initially high-confidence Paddle results.
    for document in dataset.documents:
        form_type = document_manifest[document.document_id]["form_type"]
        contract = field_contract["forms"][form_type]["fields"]
        for field in document.fields:
            field_spec = contract.get(field.field_name, {})
            candidates = field.metadata.get("ocr_candidates", [])
            if field.field_name in {"patient_first", "patient_last"}:
                selected = next(
                    (candidate for candidate in candidates if candidate.get("selected")),
                    None,
                )
                if selected and selected.get("raw"):
                    semantic_value = normalize_atomic(
                        field.field_name, str(selected["raw"])
                    )
                    if _valid(field.field_name, semantic_value):
                        field.raw_value = semantic_value
                        field.normalized_value = None
            agreement: dict[str, set[str]] = defaultdict(set)
            for candidate in candidates:
                value = str(candidate.get("value") or "")
                if field.field_name in {"patient_first", "patient_last"}:
                    value = normalize_atomic(
                        field.field_name,
                        str(candidate.get("raw") or value),
                    )
                engine = str(candidate.get("engine") or "").split("_psm_")[0]
                if value:
                    agreement[value].add(engine)
            hard_valid = _valid(field.field_name, str(field.raw_value or ""))
            sufficient_evidence = len(agreement[str(field.raw_value or "")]) >= 2
            reference_verified = bool(
                field.metadata.get("authoritative_reference_match", False)
            )
            name_requires_reference = (
                field_spec.get("type") == "person_name" and not reference_verified
            )
            if field_spec.get("critical") and not (
                hard_valid and sufficient_evidence and not name_requires_reference
            ):
                field.accepted = False
                field.validation_result = "NEEDS_REVIEW"
                field.metadata["disposition"] = "HUMAN_REVIEW_REQUIRED"
                field.metadata["disposition_reason"] = (
                    "person_name_requires_authoritative_reference_match"
                    if name_requires_reference
                    else "critical_field_requires_hard_validation_and_two_independent_engines"
                )
            elif field.accepted and hard_valid:
                field.metadata["disposition"] = "VALIDATED_AUTOMATICALLY"

    args.output.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
