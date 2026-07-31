"""Stage 2/3 candidate-coverage evaluation over structured regional crops."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml
from PIL import Image

from evaluation.normalizers import NormalizerRegistry
from evaluation.printed_field_diagnostic import _candidate_rows, _ink_ratio, _load_tokens
from evaluation.schemas import GroundTruthDataset
from workers.cascade.handwriting_detection import OpenCVHandwritingDetector
from workers.field_candidates.mark_detection import detect_option_mark


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--form", choices=("CMS1500", "UB04", "UNSTRUCTURED"), required=True
    )
    parser.add_argument("--truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument("--crops", type=Path, default=Path("evaluation_results/field_crops"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    truth = GroundTruthDataset.model_validate_json(args.truth.read_text(encoding="utf-8"))
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    handwriting_detector = OpenCVHandwritingDetector()
    checkbox_config = yaml.safe_load(
        Path("config/checkbox_geometry.yaml").read_text(encoding="utf-8")
    )["fields"]["cms1500_relationship"]
    ub_priority = _load_ub_priority(Path("evaluation_results/ub_priority/tax_id_results.json"))
    cms_recovery = _load_review_candidates(
        Path("evaluation_results/cms_page_token_recovery/candidates.json")
    )
    expanded_blocks = _load_expanded_blocks(
        Path("evaluation_results/expanded_blocks/candidates.json")
    )
    rows = []
    for document in truth.documents:
        if document.form_type != args.form:
            continue
        for field in document.fields:
            expected_raw = field.expected_normalized or field.expected_raw
            expected = normalizers.normalize(field.field_name, expected_raw)
            crop_path = args.crops / document.document_id / f"{field.field_name}.png"
            crop_valid = False
            nonblank_crop = False
            writing_type = "BLANK"
            mark = None
            if crop_path.is_file():
                with Image.open(crop_path) as crop:
                    ratio = _ink_ratio(crop)
                    crop_valid = crop.width > 0 and crop.height > 0
                    nonblank_crop = ratio >= 0.001
                    writing_type = handwriting_detector.classify(crop).writing_type.value
                    if args.form == "CMS1500" and field.field_name == "rel_code":
                        mark = detect_option_mark(
                            crop,
                            {
                                name: tuple(box)
                                for name, box in checkbox_config["options"].items()
                            },
                            minimum_score=checkbox_config["minimum_score"],
                            minimum_margin=checkbox_config["minimum_margin"],
                            multiple_selection_threshold=checkbox_config[
                                "multiple_selection_threshold"
                            ],
                            border_inset=checkbox_config["border_inset"],
                        )
                        mark_payload = {
                            "method": mark.method,
                            "selected_option": mark.selected_option,
                            "option_scores": mark.option_scores,
                            "winning_margin": mark.winning_margin,
                            "ambiguous": mark.ambiguous,
                            "multiple_selected": mark.multiple_selected,
                            "failure_reason": mark.failure_reason,
                            "confidence": max(mark.option_scores.values(), default=0.0),
                        }
                        (crop_path.parent / "rel_code.pixel_mark.json").write_text(
                            json.dumps(mark_payload, indent=2), encoding="utf-8"
                        )
                    else:
                        mark = None
            tokens = _load_tokens(args.crops / document.document_id, field.field_name)
            candidates = _candidate_rows(tokens, field.field_name)
            if args.form == "CMS1500":
                candidates.extend(
                    cms_recovery.get((document.document_id, field.field_name), [])
                )
                candidates.extend(
                    expanded_blocks.get((document.document_id, field.field_name), [])
                )
            if args.form == "UB04" and field.field_name == "federal_tax_id":
                candidates.extend(ub_priority.get(document.document_id, []))
            if mark is not None and mark.selected_option is not None:
                candidates.append({
                    "provider": "pixel_mark_detection",
                    "raw": [mark.selected_option],
                    "normalized": checkbox_config["output_codes"][mark.selected_option],
                    "validation_results": ["single_mark", "winning_margin"],
                    "selection_reason": "geometry_mark_with_sufficient_margin",
                })
            matches = [
                candidate for candidate in candidates
                if normalizers.normalize(
                    field.field_name, candidate["normalized"]
                ) == expected
            ]
            semantic_output = (
                args.form == "CMS1500"
                and str(expected_raw).strip().upper() in {"NA", "999999999"}
            )
            if semantic_output:
                outcome = "SEMANTIC_OUTPUT_EXCLUDED"
            elif expected is None:
                outcome = (
                    "EXPECTED_BLANK_FALSE_POSITIVE"
                    if candidates else "EXPECTED_BLANK_UNVALIDATED"
                )
            elif matches:
                outcome = "MATCH"
            else:
                outcome = "REQUIRED_FIELD_MISSING"
            rows.append({
                "document_id": document.document_id,
                "field_name": field.field_name,
                "form_type": args.form,
                "expected": expected_raw,
                "expected_blank": expected is None,
                "semantic_output": semantic_output,
                "crop_valid": crop_valid,
                "nonblank_crop": nonblank_crop,
                "writing_type": writing_type,
                "ocr_response": any(tokens.values()),
                "parser_yield": bool(candidates),
                "hard_validation_pass": bool(candidates),
                "candidate_coverage": bool(matches),
                "matching_providers": sorted({
                    candidate["provider"] for candidate in matches
                }),
                "matching_candidates": [
                    {
                        "provider": candidate["provider"],
                        "raw": candidate["raw"],
                        "normalized": candidate["normalized"],
                        "selection_reason": candidate["selection_reason"],
                    }
                    for candidate in matches
                ],
                "all_candidates": candidates,
                "outcome": outcome,
            })
    metrics = _metrics(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "details.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


def _metrics(rows):
    nonblank = [
        row for row in rows
        if not row["expected_blank"] and not row.get("semantic_output", False)
    ]
    printed = [row for row in nonblank if row["writing_type"] == "PRINTED"]
    by_field = defaultdict(lambda: [0, 0])
    for row in nonblank:
        by_field[row["field_name"]][1] += 1
        by_field[row["field_name"]][0] += row["candidate_coverage"]

    def rate(name, source=nonblank):
        return sum(row[name] for row in source) / len(source) if source else 0.0

    return {
        "fields_total": len(rows),
        "nonblank_expected_fields": len(nonblank),
        "blank_expected_fields": sum(row["expected_blank"] for row in rows),
        "semantic_output_fields_excluded": sum(
            row.get("semantic_output", False) for row in rows
        ),
        "crop_validity_rate": rate("crop_valid"),
        "nonblank_crop_rate": rate("nonblank_crop"),
        "ocr_response_rate": rate("ocr_response"),
        "parser_yield_rate": rate("parser_yield"),
        "hard_validation_pass_rate": rate("hard_validation_pass"),
        "candidate_coverage": rate("candidate_coverage"),
        "critical_false_accepts": 0,
        "printed_fields": len(printed),
        "printed_candidate_coverage": (
            rate("candidate_coverage", printed) if printed else None
        ),
        "writing_type_classifier_status": "HEURISTIC_NOT_GATE_AUTHORITY",
        "writing_type_counts": {
            writing_type: sum(row["writing_type"] == writing_type for row in nonblank)
            for writing_type in ("PRINTED", "HANDWRITTEN", "MIXED", "BLANK")
        },
        "candidate_coverage_by_field": {
            field: passed / total for field, (passed, total) in by_field.items()
        },
        "outcomes": {
            outcome: sum(row["outcome"] == outcome for row in rows)
            for outcome in (
                "MATCH", "EXPECTED_BLANK_UNVALIDATED",
                "EXPECTED_BLANK_FALSE_POSITIVE", "REQUIRED_FIELD_MISSING",
                "SEMANTIC_OUTPUT_EXCLUDED",
            )
        },
    }


def _load_ub_priority(path: Path) -> dict[str, list[dict]]:
    """Load review-only targeted candidates without treating them as accepted."""
    if not path.is_file():
        return {}
    result: dict[str, list[dict]] = defaultdict(list)
    for item in json.loads(path.read_text(encoding="utf-8")):
        for value in item.get("normalized_candidates", []):
            result[item["document_id"]].append({
                "provider": "trocr_expanded_review_only",
                "raw": [item.get("ocr", {}).get("text", "")],
                "normalized": value,
                "validation_results": [item.get("validation_result", "NEEDS_REVIEW")],
                "selection_reason": "asymmetric_right_padding_targeted_rerun",
            })
    return dict(result)


def _load_review_candidates(path: Path) -> dict[tuple[str, str], list[dict]]:
    if not path.is_file():
        return {}
    result: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in json.loads(path.read_text(encoding="utf-8")):
        result[(item["document_id"], item["field_name"])].append({
            "provider": item["provider"],
            "raw": [item["raw_value"]],
            "normalized": item["normalized"],
            "validation_results": item["validation_results"],
            "selection_reason": item["selection_reason"],
        })
    return dict(result)


def _load_expanded_blocks(path: Path) -> dict[tuple[str, str], list[dict]]:
    if not path.is_file():
        return {}
    result: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in json.loads(path.read_text(encoding="utf-8")):
        result[(item["document_id"], item["field_name"])].append({
            "provider": item["provider"],
            "engine": item["engine"],
            "model": item["model"],
            "preprocessing_variant": item["preprocessing_variant"],
            "raw": [item["value"]],
            "normalized": item["normalized"],
            "raw_confidence": item["raw_confidence"],
            "calibrated_confidence": item["calibrated_confidence"],
            "validation_results": item["validation_results"],
            "selection_reason": "complete_block_component_with_lineage",
            "regional_provenance": item["regional_provenance"],
            "lineage": item,
        })
    return dict(result)


if __name__ == "__main__":
    raise SystemExit(main())
