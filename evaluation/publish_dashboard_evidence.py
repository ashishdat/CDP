"""Publish governed metrics and image lineage for the React evaluation dashboard."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _asset(source_value: object, asset_dir: Path) -> str | None:
    if not source_value:
        return None
    source = Path(str(source_value).replace("\\", "/"))
    if not source.is_file():
        return None
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    target = asset_dir / f"{digest}{source.suffix.lower()}"
    if not target.is_file():
        shutil.copy2(source, target)
    return f"/reports/evidence/{target.name}"


def publish(
    report_path: Path,
    details_path: Path,
    optimization_path: Path,
    local_first_path: Path = Path("evaluation_results/local_first_v7/metrics.json"),
    runtime_report_path: Path = Path("evaluation_results/evaluation.json"),
) -> dict:
    report = _json(report_path)
    details = _json(details_path)
    optimization = _json(optimization_path)
    final_validation_path = Path(
        "evaluation_results/reference_validation_six/final_current_sample_metrics.json"
    )
    final_validation = (
        _json(final_validation_path) if final_validation_path.is_file() else None
    )
    local_first = _json(local_first_path) if local_first_path.is_file() else None
    asset_dir = report_path.parent / "evidence"
    asset_dir.mkdir(parents=True, exist_ok=True)

    evidence = []
    for row in details:
        identity = row.get("field_identity") or {}
        provenance = row.get("provenance") or {}
        document_id = identity.get("document_id", "unknown")
        field_name = identity.get("semantic_field", "unknown")
        fallback_page = Path("evaluation_results/assets") / f"{document_id}.png"
        fallback_crop = Path("evaluation_results/field_crops") / str(document_id) / f"{field_name}.png"
        original_source = provenance.get("original_page")
        crop_source = provenance.get("crop_path") or provenance.get("crop_reference")
        if not original_source and fallback_page.is_file():
            original_source = fallback_page
        if not crop_source and fallback_crop.is_file():
            crop_source = fallback_crop
        evidence.append({
            "document_id": document_id,
            "form_type": identity.get("document_family", "unknown"),
            "field_name": field_name,
            "expected_value": row.get("expected_value"),
            "extracted_value": row.get("selected_value"),
            "normalized_value": row.get("normalized_value"),
            "extraction_method": row.get("provider") or "unknown",
            "confidence": row.get("confidence"),
            "status": "MATCH" if row.get("selected_correct") else row.get("outcome", "UNRESOLVED"),
            "correct": bool(row.get("selected_correct")),
            "original_page_url": _asset(original_source, asset_dir),
            "row_context_url": _asset(provenance.get("row_context_path"), asset_dir),
            "crop_url": _asset(crop_source, asset_dir),
        })

    total = int(optimization["total_fields"])
    azure_recoveries = int(optimization["azure_correct_recoveries"])
    report["field_evidence"] = evidence
    if local_first:
        report["llm_diverted_fields"] = local_first["llm_fields_after"]
        report["llm_diversion_rate"] = local_first["llm_diversion_rate_after"]
        report["accuracy_after_fallback"] = local_first["accuracy_after"]
    if final_validation:
        local_fields = int(local_first.get("local_extraction_correct_fields", 0)) if local_first else 0
        if not local_fields:
            local_fields = sum(int(final_validation[key]) for key in (
                "frozen_correct_fields",
                "ocr_crop_recoveries",
                "deterministic_parser_and_geometry_recoveries",
            ))
        report["local_extraction_correct_fields"] = local_fields
        report["local_extraction_accuracy"] = local_fields / int(
            final_validation["total_fields"]
        )
        report["local_extraction_definition"] = (
            "OCR plus deterministic parsing and geometry; excludes LLM, "
            "reference verification and semantic output projection."
        )
    report["optimization_metrics"] = {
        "baseline_ocr_correct_fields": int(optimization["baseline_correct"]),
        "baseline_ocr_accuracy": optimization["baseline_correct"] / total,
        "llm_attempted_fields": int(report.get("llm_diverted_fields", 0)),
        "llm_diversion_rate": float(report.get("llm_diversion_rate", 0.0)),
        "llm_incremental_recoveries": azure_recoveries,
        "llm_incremental_recovery_rate": azure_recoveries / total,
        "paddle_incremental_recoveries": int(optimization["paddle_correct_recoveries"]),
        "deterministic_incremental_recoveries": int(
            optimization["deterministic_derived_recoveries"]
        ),
        "local_union_incremental_recoveries": None,
        "target_llm_diversion_rate": 0.08,
        "promotion_status": (
            "ACTIVE_CURRENT_SAMPLE_REPLAY_HOLDOUT_PENDING" if local_first
            else "SHADOW_ONLY_PENDING_UNTOUCHED_HOLDOUT"
        ),
    }
    if local_first:
        report["optimization_metrics"].update({
            "llm_incremental_recoveries": local_first.get(
                "llm_routed_correct_fields", azure_recoveries
            ),
            "llm_incremental_recovery_rate": local_first.get(
                "llm_routed_correct_fields", azure_recoveries
            ) / total,
            "historical_llm_attempts": local_first["historical_llm_attempts"],
            "unique_llm_eligible_fields_before": local_first["unique_llm_eligible_fields_before"],
            "duplicate_requests_eliminated": local_first["duplicate_requests_eliminated"],
            "reference_short_circuits": local_first["reference_short_circuits"],
            "local_route_short_circuits": local_first["validated_local_route_short_circuits"],
            "semantic_short_circuits": local_first["semantic_short_circuits"],
            "reference_before_llm": local_first.get("reference_before_llm", False),
            "exact_cache_eligible_repeat_fields": local_first.get(
                "exact_cache_eligible_repeat_fields", 0
            ),
            "repeat_llm_fields_after_warm_cache": local_first.get(
                "repeat_llm_fields_after_warm_cache"
            ),
            "gates": local_first["gates"],
        })
        cost = report.get("cost_analysis") or {}
        prior_fields = local_first["historical_llm_attempts"]
        if prior_fields and cost.get("actual_run_cost_usd") is not None:
            projected = cost["actual_run_cost_usd"] * local_first["llm_fields_after"] / prior_fields
            cost["projected_optimized_run_cost_usd"] = projected
            pages = report.get("operational_metrics", {}).get("total_pages_processed") or 0
            cost["projected_optimized_cost_per_page_usd"] = projected / pages if pages else None
    report.setdefault("report_metadata", {})["generated_at"] = datetime.now(UTC).isoformat()
    report["report_metadata"]["scope"] = "CURRENT_LABELED_SAMPLE_ONLY"
    report["report_metadata"]["production_generalization_claim"] = False
    report["report_metadata"]["optimization_measurement"] = (
        "CURRENT_SAMPLE_POLICY_REPLAY" if local_first else "NOT_AVAILABLE"
    )
    rendered_report = json.dumps(report, indent=2)
    report_path.write_text(rendered_report, encoding="utf-8")
    if runtime_report_path.resolve() != report_path.resolve():
        runtime_report_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_report_path.write_text(rendered_report, encoding="utf-8")
    return {
        "published_fields": len(evidence),
        "fields_with_page_images": sum(bool(row["original_page_url"]) for row in evidence),
        "fields_with_crop_images": sum(bool(row["crop_url"]) for row in evidence),
        "assets": len(list(asset_dir.iterdir())),
        "report": str(report_path),
        "runtime_report": str(runtime_report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report", type=Path,
        default=Path("apps/evaluation_ui/public/reports/evaluation.json"),
    )
    parser.add_argument(
        "--details", type=Path,
        default=Path("evaluation_results/reporting_v3/details.json"),
    )
    parser.add_argument(
        "--optimization", type=Path,
        default=Path("evaluation_results/unresolved_union_latest/metrics.json"),
    )
    args = parser.parse_args()
    print(json.dumps(publish(args.report, args.details, args.optimization), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
