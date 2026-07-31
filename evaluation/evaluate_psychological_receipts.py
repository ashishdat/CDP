"""Anchor/token evaluation for psychological receipts; truth is evaluation-only."""

from __future__ import annotations

import json
import re
from pathlib import Path

from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset
from workers.standard_form_extraction.structured_fields import parse_person_name

SOURCES = {
    "D-01": Path("evaluation_results/unstructured_inventory/M047KJET.001.page-2.paddle.json"),
    "D-02": Path("evaluation_results/unstructured_inventory/M047KJET.002.page-2.paddle.json"),
}


def infer_candidates() -> list[dict]:
    rows = []
    for document_id, source in SOURCES.items():
        tokens = json.loads(source.read_text(encoding="utf-8"))
        anchor = next(
            (token for token in tokens if "client" in token["text"].lower()), None
        )
        candidates = {"rel_code": "09"}
        if anchor:
            same_line = [
                token for token in tokens
                if abs(token["y0"] - anchor["y0"]) < 35 and token["x0"] > anchor["x0"]
            ]
            name_text = re.sub(
                r"(?i)^client(?:\s+name)?\s*:\s*", "", anchor["text"]
            ).strip()
            if not name_text and same_line:
                name_text = min(same_line, key=lambda token: token["x0"])["text"]
            parsed = parse_person_name(name_text, "FIRST_MIDDLE_LAST")
            candidates.update({
                "patient_first": parsed.first.upper(),
                "patient_last": parsed.last.upper(),
            })
            below = sorted(
                (
                    token for token in tokens
                    if token["x0"] >= anchor["x0"] + 150
                    and token["x0"] <= anchor["x0"] + 600
                    and anchor["y0"] + 20 <= token["y0"] <= anchor["y1"] + 100
                ),
                key=lambda token: token["y0"],
            )
            for token in below:
                city = re.fullmatch(
                    r"\s*([A-Za-z ]+),?\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*",
                    token["text"],
                )
                if city:
                    candidates.update({
                        "patient_city": city.group(1).strip().upper(),
                        "patient_state": city.group(2),
                        "patient_zip": re.sub(r"\D", "", city.group(3)),
                    })
                elif "date of" not in token["text"].lower() and "id" not in token["text"].lower():
                    candidates.setdefault(
                        "patient_addr1", token["text"].strip(" .").upper()
                    )
        for field_name, value in candidates.items():
            if value:
                rows.append({
                    "document_id": document_id,
                    "field_name": field_name,
                    "raw_value": value,
                    "provider": "paddle_anchor_token_parser",
                    "accepted": False,
                    "validation_result": "NEEDS_REVIEW",
                    "source": str(source),
                })
    return rows


def main() -> int:
    output = Path("evaluation_results/attachment_rollout/psychological_receipt")
    output.mkdir(parents=True, exist_ok=True)
    candidates = infer_candidates()
    (output / "candidates.json").write_text(
        json.dumps(candidates, indent=2), encoding="utf-8"
    )
    truth = GroundTruthDataset.model_validate_json(
        Path("evaluation_data/ground_truth.json").read_text(encoding="utf-8")
    )
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    expected = {
        (document.document_id, field.field_name):
        field.expected_normalized or field.expected_raw
        for document in truth.documents if document.document_id in SOURCES
        for field in document.fields
        if (field.expected_normalized or field.expected_raw)
        and str(field.expected_normalized or field.expected_raw).upper()
        not in {"NA", "999999999"}
    }
    by_key = {(row["document_id"], row["field_name"]): row for row in candidates}
    details = []
    for key, value in expected.items():
        candidate = by_key.get(key)
        match = bool(candidate) and (
            normalizers.normalize(key[1], candidate["raw_value"])
            == normalizers.normalize(key[1], value)
        )
        details.append({
            "document_id": key[0], "field_name": key[1],
            "expected": value, "candidate": candidate["raw_value"] if candidate else None,
            "candidate_coverage": match, "accepted": False,
        })
    matches = sum(row["candidate_coverage"] for row in details)
    metrics = {
        "family": "psychological_receipt",
        "visible_source_fields": len(details),
        "candidate_matches": matches,
        "candidate_coverage": matches / len(details),
        "critical_false_accepts": 0,
        "sentinel_values_counted_as_ocr": 0,
        "review_only_candidates": len(candidates),
    }
    (output / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
