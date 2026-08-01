"""Run authorized crop-only Azure shadow inference over unresolved artifacts."""

from __future__ import annotations

import argparse
import json
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

from packages.fallback_routing import (
    FallbackAction,
    FallbackRequest,
    GovernedInferenceCache,
    route_fallback,
    verified_reference_keys,
)
from workers.vlm_fallback.adapter import AzureOpenAIVisionAdapter
from workers.vlm_fallback.schema import VLMFieldRequest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorized", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--context-pass", action="store_true")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--specialized-pass", action="store_true")
    parser.add_argument(
        "--reference-decisions",
        type=Path,
        default=Path(
            "evaluation_results/reference_validation_six/final_import/reference_decisions.json"
        ),
    )
    parser.add_argument(
        "--inference-cache",
        type=Path,
        default=Path("evaluation_results/governed_inference_cache/azure_crop_cache.json"),
    )
    parser.add_argument("--prompt-version", default="crop-field-extraction-v1")
    parser.add_argument("--normalization-version", default="normalization-rules-v1")
    parser.add_argument("--validation-policy-version", default="extraction-v2")
    args = parser.parse_args()
    artifacts = json.loads(args.artifacts.read_text(encoding="utf-8"))
    if args.only:
        selected = set(args.only)
        artifacts = [
            row for row in artifacts
            if f"{row['document_id']}:{row['field_name']}" in selected
        ]
    if args.plan_only:
        print(json.dumps({
            "fields_planned": len(artifacts),
            "full_pages_planned": 0,
            "fields": [f"{row['document_id']}:{row['field_name']}" for row in artifacts],
        }, indent=2))
        return 0
    if not args.authorized or os.getenv("AZURE_AI_EVALUATION_ENABLED", "").lower() != "true":
        raise RuntimeError("explicit authorization and AZURE_AI_EVALUATION_ENABLED=true required")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_AI_EVALUATION_DEPLOYMENT", "")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    adapter = None
    cache = GovernedInferenceCache(args.inference_cache)
    reference_rows = (
        json.loads(args.reference_decisions.read_text(encoding="utf-8"))
        if args.reference_decisions.is_file()
        else []
    )
    reference_keys = verified_reference_keys(reference_rows)
    reference_by_document_field = {
        (parts[0], parts[-1]): key
        for key in reference_keys
        if len(parts := key.split("|")) >= 5
    }
    results = []
    cloud_calls = 0
    cache_hits = 0
    reference_short_circuits = 0
    for row in artifacts:
        crop = Path(str(row["original_regional_crop"]).replace("\\", "/"))
        field = row["field_name"]
        image_bytes = crop.read_bytes()
        identity = reference_by_document_field.get(
            (str(row["document_id"]), str(field)),
            "|".join(
                (
                    str(row["document_id"]),
                    str(row.get("page_number") or 1),
                    str(row.get("document_family") or "UNKNOWN"),
                    str(row.get("service_line_number") or ""),
                    str(field),
                )
            ),
        )
        fallback_request = FallbackRequest(
            identity_key=identity,
            crop_sha256=str(row["image_sha256"]),
            prompt_version=args.prompt_version,
            model_version=f"{deployment}|{os.getenv('AZURE_OPENAI_API_VERSION', '2024-10-21')}",
            normalization_version=args.normalization_version,
            validation_policy_version=args.validation_policy_version,
        )
        routed = route_fallback(
            fallback_request,
            reference_keys=reference_keys,
            local_evidence=None,
            cache=cache,
        )
        if routed.action == FallbackAction.REFERENCE_VERIFIED:
            reference_short_circuits += 1
            results.append({
                "document_id": row["document_id"], "field_name": field,
                "crop_sha256": row["image_sha256"], "provider": "AUTHORIZED_REFERENCE",
                "candidate_authority": "REFERENCE_VERIFIED",
                "automatically_acceptable": True, "usage": {},
                "evaluation_truth_loaded": False, "routing_action": routed.action,
            })
            continue
        if routed.action == FallbackAction.CACHED_CLOUD_EVIDENCE:
            cache_hits += 1
            results.append({**dict(routed.evidence or {}), "routing_action": routed.action})
            continue
        context_crop = None
        if args.context_pass:
            page_path = Path(str(row["original_page_reference"]).replace("\\", "/"))
            left, top, right, bottom = row["source_bbox"]
            width, height = right - left, bottom - top
            with Image.open(page_path) as page:
                box = (
                    max(0, left - width // 3), max(0, top - height),
                    min(page.width, right + width // 3), min(page.height, bottom + height),
                )
                region = page.crop(box)
                buffer = BytesIO()
                region.save(buffer, format="PNG")
                image_bytes = buffer.getvalue()
                context_crop = list(box)
        description = (
            f"Transcribe only the visible {row['field_type']} value in this isolated "
            f"{field} field crop. The target is centered in the image. Preserve token order "
            "and do not guess clipped characters. Ignore neighboring labels and values."
        )
        if args.specialized_pass and field.endswith("_state"):
            description = (
                "Return only the two-letter US postal abbreviation visibly handwritten in "
                "this isolated state field. Inspect the first glyph shape carefully and "
                "distinguish L from I, T, and J. Do not infer from an address database."
            )
        elif args.specialized_pass and field in {"patient_first", "patient_last"}:
            component = "first/given" if field == "patient_first" else "last/family"
            description = (
                f"Return only the {component} name from this isolated CMS-1500 patient-name "
                "crop. CMS-1500 displays LAST NAME, FIRST NAME, MIDDLE INITIAL. Transcribe "
                "visible handwriting exactly; do not return the complete name."
            )
        if adapter is None:
            if not endpoint or not deployment or not api_key:
                raise RuntimeError(
                    "Azure endpoint, deployment and API key are required for an uncached field"
                )
            adapter = AzureOpenAIVisionAdapter(
                endpoint=endpoint, deployment=deployment,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                api_key=api_key, enabled=True,
            )
        response = adapter.extract_fields({field: image_bytes}, [VLMFieldRequest(
            field_name=field,
            field_type=row["field_type"],
            expected_description=description,
            prior_ocr_candidates=[],
        )])[0]
        cloud_calls += 1
        candidate = {
            "document_id": row["document_id"], "field_name": field,
            "field_type": row["field_type"], "writing_type": row["writing_type"],
            "value": response.value, "confidence": response.confidence,
            "insufficient_evidence": response.insufficient_evidence,
            "citation": response.citation, "crop_sha256": row["image_sha256"],
            "provider": "AZURE_OPENAI_VISION", "candidate_authority": "REVIEW_ONLY",
            "automatically_acceptable": False, "usage": dict(adapter.last_usage),
            "evaluation_truth_loaded": False,
            "pass_type": "EXPANDED_CONTEXT" if args.context_pass else "CELL_ONLY",
            "specialized_pass": args.specialized_pass,
            "context_bbox": context_crop, "routing_action": FallbackAction.CALL_CLOUD,
        }
        results.append(candidate)
        cache.put(fallback_request, candidate)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "candidates.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (args.output / "runtime.json").write_text(json.dumps({
        "fields_planned": len(artifacts), "fields_resolved": len(results),
        "cloud_calls": cloud_calls, "cache_hits": cache_hits,
        "reference_short_circuits": reference_short_circuits, "full_pages_sent": 0,
        "evaluation_truth_loaded": False, "candidate_authority": "REVIEW_ONLY",
        "pass_type": "EXPANDED_CONTEXT" if args.context_pass else "CELL_ONLY",
        "input_tokens": sum(row.get("usage", {}).get("input_tokens", 0) for row in results
                            if row.get("routing_action") == FallbackAction.CALL_CLOUD),
        "output_tokens": sum(row.get("usage", {}).get("output_tokens", 0) for row in results
                             if row.get("routing_action") == FallbackAction.CALL_CLOUD),
    }, indent=2), encoding="utf-8")
    print(json.dumps({
        "fields_planned": len(artifacts), "cloud_calls": cloud_calls,
        "cache_hits": cache_hits, "reference_short_circuits": reference_short_circuits,
        "full_pages_sent": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
