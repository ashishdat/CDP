"""Create the checksum-pinned extraction-v2 release manifest."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from packages.release_freeze import sha256_file

FROZEN_CONFIGS = (
    "config/router_frozen_v1.yaml",
    "config/reconciliation_policy_v2.yaml",
    "config/templates/cms1500_v02_12.yaml",
    "config/templates/ub04_v2014.yaml",
    "config/handwriting_model_families.yaml",
    "config/validation/cms1500_thresholds.yaml",
    "config/validation/ub04_thresholds.yaml",
    "config/sentinel_projection_rules.yaml",
)


def main() -> int:
    metrics = json.loads(
        Path("evaluation_results/current_v2_router/metrics.json").read_text()
    )
    channels = json.loads(Path("evaluation_results/accuracy_channels.json").read_text())
    manifest = {
        "pipeline_version": "extraction-v2",
        "status": "FROZEN",
        "router_policy_version": "router_frozen_v1",
        "reconciliation_version": "reconciliation_v2.1",
        "template_versions": {"cms1500": "02-12", "ub04": "2014"},
        "ocr_models": {
            "primary": {"engine": "PaddleOCR", "model": "PP-OCRv4", "runtime": "paddleocr-2.x"},
            "secondary": {"engine": "Tesseract", "model": "field-specific-psm", "runtime": "external"},
            "handwriting": {
                "engine": "TrOCR",
                "model": "microsoft/trocr-base-handwritten",
                "runtime": "transformers-4.x",
                "authority": "REVIEW_ONLY_UNTIL_DOMAIN_HOLDOUT_PROMOTION",
            },
            "attachment_printed": {
                "engine": "TrOCR",
                "model": "microsoft/trocr-base-printed",
                "authority": "REVIEW_ONLY",
            },
            "optional_layout": {"engine": "Docling", "status": "PILOT_DISABLED"},
        },
        "handwriting_cascade_version": "field-cascade-v1",
        "validation_rule_version": "validation-v1",
        "output_projection_version": "sentinel-projection-v1-pending-authorization",
        "release_timestamp": datetime.now(UTC).isoformat(),
        "configuration_hashes": {
            path: sha256_file(Path(path)) for path in FROZEN_CONFIGS
        },
        "evaluation_split_version": "evaluation_data/ground_truth.json:current",
        "baseline_metrics": {
            "automated_accuracy": metrics["extraction_accuracy"],
            "page_accuracy": metrics["actual_page_accuracy"],
            "wrong_page_fields": metrics["wrong_page_field_count"],
            "critical_false_accepts": metrics["critical_false_accepts"],
            "reference_blocked_fields": channels["REFERENCE_BLOCKED_FIELDS"],
            "human_review_required_fields": channels["HUMAN_REVIEW_REQUIRED_FIELDS"],
            "semantic_review_fields": channels["SEMANTIC_REVIEW_FIELDS"],
            "final_validated_accuracy": None,
        },
        "known_limitations": [
            "Authorized member/provider/address datasets are not configured.",
            "Fourteen fields require human review, including one derived PO-box candidate.",
            "Literal Unknown address semantics require specification/business approval.",
            "Generic TrOCR handwriting output is non-authoritative.",
            "Docling remains a disabled additive pilot.",
        ],
        "change_control": {
            "unversioned_changes_permitted": False,
            "new_version_required_for": [
                "router", "reconciliation", "parser", "model",
                "validation_rule", "projection_rule",
            ],
        },
    }
    output = Path("config/releases/extraction-v2.yaml")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    print(f"Wrote frozen release manifest to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
