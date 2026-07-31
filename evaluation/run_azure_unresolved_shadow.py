"""Run authorized crop-only Azure shadow inference over unresolved artifacts."""

from __future__ import annotations

import argparse
import json
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

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
    if not endpoint or not deployment or not api_key:
        raise RuntimeError("Azure endpoint, deployment and API key are required")
    adapter = AzureOpenAIVisionAdapter(
        endpoint=endpoint, deployment=deployment,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        api_key=api_key, enabled=True,
    )
    results = []
    for row in artifacts:
        crop = Path(str(row["original_regional_crop"]).replace("\\", "/"))
        field = row["field_name"]
        image_bytes = crop.read_bytes()
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
        response = adapter.extract_fields({field: image_bytes}, [VLMFieldRequest(
            field_name=field,
            field_type=row["field_type"],
            expected_description=description,
            prior_ocr_candidates=[],
        )])[0]
        results.append({
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
            "context_bbox": context_crop,
        })
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "candidates.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (args.output / "runtime.json").write_text(json.dumps({
        "fields_attempted": len(results), "full_pages_sent": 0,
        "evaluation_truth_loaded": False, "candidate_authority": "REVIEW_ONLY",
        "pass_type": "EXPANDED_CONTEXT" if args.context_pass else "CELL_ONLY",
        "input_tokens": sum(row["usage"].get("input_tokens", 0) for row in results),
        "output_tokens": sum(row["usage"].get("output_tokens", 0) for row in results),
    }, indent=2), encoding="utf-8")
    print(json.dumps({"fields_attempted": len(results), "full_pages_sent": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
