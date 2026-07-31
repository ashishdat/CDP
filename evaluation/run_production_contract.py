"""Assemble frozen production predictions for a contract without evaluation truth."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from PIL import Image

from evaluation.reporting_v3_common import (
    contract_checksum,
    identity_key,
    normalize,
    sha256_file,
)
from workers.table_extraction.field_candidate_parsing import parsed_alternatives
from workers.table_extraction.semantic_blank import detect_semantic_blank


def _table_predictions(contract: dict) -> dict[tuple, dict]:
    pilot = Path("evaluation_results/table_crop_quality_pilot")
    manifest = {
        row["candidate_id"]: row
        for row in (
            json.loads(line)
            for line in (pilot / "pilot_manifest.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    decisions = {
        row["candidate_id"]: row
        for row in json.loads(
            (pilot / "ocr_shadow/cascade_decisions.json").read_text(encoding="utf-8")
        )
    }
    paddle = json.loads(
        (pilot / "ocr_shadow/ppocr_candidates.json").read_text(encoding="utf-8")
    )
    tesseract = json.loads(
        (pilot / "ocr_shadow/candidates.json").read_text(encoding="utf-8")
    )
    raw_by_id: dict[str, list[dict]] = {}
    for row in paddle + tesseract:
        raw_by_id.setdefault(row["candidate_id"], []).append(row)
    azure_path = Path("evaluation_results/azure_vlm_shadow/candidates.json")
    azure_by_identity = {}
    if azure_path.is_file():
        azure_by_identity = {
            identity_key(row["field_identity"]): row
            for row in json.loads(azure_path.read_text(encoding="utf-8"))
        }
    output = {}
    promotion = yaml.safe_load(
        Path("config/evaluation/table_promotion_v3.yaml").read_text(encoding="utf-8")
    )
    for field in contract["fields"]:
        candidate_id = field.get("candidate_id")
        if not candidate_id:
            continue
        item, decision = manifest[candidate_id], decisions[candidate_id]
        identity = field["field_identity"]
        candidates = raw_by_id.get(candidate_id, [])
        azure = azure_by_identity.get(identity_key(identity))
        if azure:
            candidates.append({
                "engine": "azure_openai_vision",
                "model": "configured-deployment",
                "model_version": "azure-shadow-v1",
                "independence_group": "AZURE_OPENAI_VISION",
                "raw_value": azure["value"],
                "raw_confidence": azure["confidence"],
                "insufficient_evidence": azure["insufficient_evidence"],
                "candidate_authority": "REVIEW_ONLY",
                "automatically_acceptable": False,
                "crop_sha256": azure["crop_sha256"],
            })
        crop_path = Path(str(item["crop_path"]).replace("\\", "/"))
        with Image.open(crop_path) as opened:
            blank = detect_semantic_blank(opened)
        blank_allowed = item["semantic_field_name"] in promotion["optional_blank_fields"]
        blank_supported = (
            blank_allowed
            and blank.is_blank
            and blank.confidence >= promotion["minimum_blank_confidence"]
        )
        if blank_supported:
            candidates.append({
                "engine": "semantic_blank_detector",
                "model": blank.policy_version,
                "model_version": blank.policy_version,
                "independence_group": "PIXEL_SEMANTIC_STATE",
                "raw_value": None,
                "raw_confidence": blank.confidence,
                "semantic_state": "BLANK",
                "candidate_authority": "REVIEW_ONLY",
                "automatically_acceptable": False,
                "validation_results": ["OPTIONAL_FIELD", "GRID_RULES_REMOVED"],
                "blank_evidence": {
                    "ink_density": blank.ink_density,
                    "substantive_components": blank.substantive_components,
                    "ignored_rule_components": blank.ignored_rule_components,
                },
            })
        derived = []
        for candidate in candidates:
            for alternative in parsed_alternatives(
                candidate.get("raw_value"), field["expected_data_type"]
            ):
                derived.append({
                    "engine": "deterministic_field_parser",
                    "model": alternative["method"],
                    "model_version": "table-v3",
                    "independence_group": "DETERMINISTIC_PARSER",
                    "raw_value": alternative["value"],
                    "raw_confidence": None,
                    "candidate_authority": "REVIEW_ONLY",
                    "automatically_acceptable": False,
                    "parent_engine": candidate["engine"],
                    "reason": alternative["reason"],
                })
        candidates = candidates + derived
        azure_supported = bool(
            azure
            and not azure["insufficient_evidence"]
            and azure["value"]
            and azure["confidence"] >= 0.90
            and decision["status"] in {"PADDLE_REVIEW_SUGGESTION", "NO_EVIDENCE"}
        )
        azure_value = azure["value"] if azure else None
        selected = (
            None if blank_supported else
            azure_value if azure_supported else
            decision.get("suggestion") or None
        )
        best = max(
            (row for row in candidates if row.get("raw_value")),
            key=lambda row: row.get("raw_confidence") or 0.0,
            default={},
        )
        if blank_supported:
            best = next(
                row for row in candidates
                if row.get("semantic_state") == "BLANK"
            )
        elif azure_supported:
            best = next(
                row for row in candidates
                if row.get("independence_group") == "AZURE_OPENAI_VISION"
            )
        output[identity_key(identity)] = {
            "field_identity": identity, "selected_value": selected,
            "normalized_value": normalize(selected, field["expected_data_type"]),
            # The table pilot remains shadow-only even when local engines agree.
            "candidate_status": (
                "REVIEW_ONLY" if selected is not None or blank_supported else "NO_EVIDENCE"
            ),
            "review_required": True, "provider": best.get("engine"),
            "provider_version": best.get("model_version"),
            "confidence": best.get("raw_confidence"),
            "validation_results": [
                "SEMANTIC_BLANK_EVIDENCE" if blank_supported else
                "AZURE_SHADOW_EVIDENCE" if azure_supported else decision["status"],
                "SHADOW_TABLE_POLICY_REVIEW_ONLY",
            ],
            "crop_quality": item["crop_quality_status"],
            "row_status": item["row_status"],
            "provenance": {
                "candidate_id": candidate_id, "original_page": item["original_page"],
                "row_context_path": item["row_context_path"],
                "crop_path": item["crop_path"], "registered_bbox": item["registered_bbox"],
                "crop_sha256": item["crop_sha256"], "raw_candidates": candidates,
            },
            "automatically_acceptable": False,
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if contract_checksum(contract) != contract["contract_sha256"]:
        raise RuntimeError("contract checksum verification failed")
    base = json.loads(
        Path("evaluation_results/predictions_v2/predictions.json").read_text(encoding="utf-8")
    )
    available = {identity_key(row["field_identity"]): row for row in base}
    available.update(_table_predictions(contract))
    predictions = []
    for field in contract["fields"]:
        key = identity_key(field["field_identity"])
        if key not in available:
            raise RuntimeError(f"missing prediction for contract field {key}")
        prediction = dict(available[key])
        prediction["expected_data_type"] = field["expected_data_type"]
        predictions.append(prediction)
    args.output.mkdir(parents=True, exist_ok=True)
    prediction_path = args.output / "predictions.json"
    prediction_path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    manifest = {
        "inference_run_id": str(uuid4()),
        "evaluation_contract_version": contract["contract_version"],
        "contract_sha256": contract["contract_sha256"],
        "prediction_artifact_sha256": sha256_file(prediction_path),
        "ground_truth_available_to_inference": False,
        "fields_attempted": len(predictions),
        "provider_versions": {
            "production": "extraction-v2", "paddle": "PP-OCRv5-server/PP-OCRv6-medium",
            "tesseract": "5.x",
        },
        "policy_versions": {
            "router": "frozen-v1", "reconciliation": "v2.1",
            "table_promotion": "shadow-review-only",
        },
        "run_timestamp": datetime.now(UTC).isoformat(),
        "command": " ".join(sys.argv),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
    }
    (args.output / "inference_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
