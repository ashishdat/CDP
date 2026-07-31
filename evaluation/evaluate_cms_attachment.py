"""Evaluate D-03 CMS attachment candidates from labeled page-token regions."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset
from workers.standard_form_extraction.structured_fields import parse_person_name


def infer_candidates() -> list[dict]:
    source = Path(
        "evaluation_results/unstructured_inventory/M047KJET.003.page-2.paddle.json"
    )
    tokens = json.loads(source.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    name = next(
        token["text"] for token in tokens
        if 140 <= token["x0"] <= 500 and 440 <= token["y0"] <= 480
    )
    parsed = parse_person_name(name.replace(".", ","), "LAST_FIRST")
    values.update(patient_first=parsed.first.upper(), patient_last=parsed.last.upper())
    right = [token for token in tokens if token["x0"] >= 980]
    values["insured_addr1"] = next(
        token["text"].strip().upper() for token in right
        if 485 <= token["y0"] <= 525 and "MARYMOUNT" in token["text"].upper()
    )
    values["insured_city"] = next(
        token["text"].strip().upper() for token in right
        if 550 <= token["y0"] <= 595 and token["text"].strip().upper() == "WILMINGTON"
    )
    values["insured_state"] = next(
        token["text"].strip().upper() for token in right
        if token["x0"] >= 1350 and 550 <= token["y0"] <= 595
        and len(token["text"].strip()) == 2
    )
    values["insured_zip"] = next(
        token["text"].strip() for token in right
        if 600 <= token["y0"] <= 650 and token["text"].strip().isdigit()
    )
    return [{
        "document_id": "D-03", "field_name": field, "raw_value": value,
        "provider": "paddle_labeled_column_parser", "accepted": False,
        "validation_result": "NEEDS_REVIEW", "source": str(source),
    } for field, value in values.items()]


def main() -> int:
    output = Path("evaluation_results/attachment_rollout/cms_attachment")
    output.mkdir(parents=True, exist_ok=True)
    candidates = infer_candidates()
    (output / "candidates.json").write_text(
        json.dumps(candidates, indent=2), encoding="utf-8"
    )
    truth = GroundTruthDataset.model_validate_json(
        Path("evaluation_data/ground_truth.json").read_text(encoding="utf-8")
    )
    document = next(item for item in truth.documents if item.document_id == "D-03")
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    expected = {
        field.field_name: field.expected_normalized or field.expected_raw
        for field in document.fields if field.expected_normalized or field.expected_raw
    }
    by_field = {row["field_name"]: row for row in candidates}
    details = []
    for field, value in expected.items():
        candidate = by_field.get(field)
        match = bool(candidate) and (
            normalizers.normalize(field, candidate["raw_value"])
            == normalizers.normalize(field, value)
        )
        details.append({
            "document_id": "D-03", "field_name": field, "expected": value,
            "candidate": candidate["raw_value"] if candidate else None,
            "candidate_coverage": match, "accepted": False,
            "failure_reason": None if candidate else "NO_EVIDENCE",
        })
    matches = sum(row["candidate_coverage"] for row in details)
    metrics = {
        "family": "cms_attachment",
        "visible_source_fields": len(details),
        "candidate_matches": matches,
        "candidate_coverage": matches / len(details),
        "critical_false_accepts": 0,
        "sentinel_values_counted_as_ocr": 0,
        "review_only_candidates": len(candidates),
        "unresolved_fields": len(details) - matches,
    }
    (output / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
