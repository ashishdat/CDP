"""Send only unresolved regional crops to authorized Azure OpenAI shadow OCR."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from workers.vlm_fallback.adapter import AzureOpenAIVisionAdapter
from workers.vlm_fallback.schema import VLMFieldRequest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorized", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    targets = [
        row for row in predictions
        if row["candidate_status"] == "REVIEW_ONLY"
        and any(
            status in {
                "PADDLE_REVIEW_SUGGESTION", "NO_EVIDENCE",
                "AZURE_SHADOW_EVIDENCE",
            }
            for status in row["validation_results"]
        )
        and row.get("provenance", {}).get("crop_path")
    ]
    if args.plan_only:
        print(json.dumps({
            "fields_planned": len(targets),
            "field_identities": [row["field_identity"] for row in targets],
            "full_pages_planned": 0,
        }, indent=2))
        return 0
    if not args.authorized or os.getenv("AZURE_AI_EVALUATION_ENABLED", "").lower() != "true":
        raise RuntimeError(
            "explicit --authorized and AZURE_AI_EVALUATION_ENABLED=true are required"
        )
    required = {
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_DEPLOYMENT": (
            os.getenv("AZURE_OPENAI_DEPLOYMENT")
            or os.getenv("AZURE_AI_EVALUATION_DEPLOYMENT")
        ),
        "AZURE_OPENAI_API_VERSION": os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-10-21"
        ),
        "AZURE_OPENAI_API_KEY": os.getenv("AZURE_OPENAI_API_KEY"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"missing Azure configuration: {', '.join(missing)}")
    adapter = AzureOpenAIVisionAdapter(
        endpoint=required["AZURE_OPENAI_ENDPOINT"] or "",
        deployment=required["AZURE_OPENAI_DEPLOYMENT"] or "",
        api_version=required["AZURE_OPENAI_API_VERSION"] or "",
        api_key=required["AZURE_OPENAI_API_KEY"] or "",
        enabled=True,
    )
    results = []
    for row in targets:
        identity = row["field_identity"]
        crop_path = Path(str(row["provenance"]["crop_path"]).replace("\\", "/"))
        request = VLMFieldRequest(
            field_name=identity["semantic_field"],
            field_type=row.get("expected_data_type", "text"),
            expected_description=(
                f"{identity['document_family']} {identity['form_locator']} "
                f"service line {identity['service_line_number']}"
            ),
            prior_ocr_candidates=[
                str(candidate["raw_value"])
                for candidate in row["provenance"].get("raw_candidates", [])
                if candidate.get("raw_value")
            ],
        )
        response = adapter.extract_fields(
            {request.field_name: crop_path.read_bytes()}, [request]
        )[0]
        results.append({
            "field_identity": identity,
            "value": response.value,
            "confidence": response.confidence,
            "insufficient_evidence": response.insufficient_evidence,
            "citation": response.citation,
            "provider": "AZURE_OPENAI_VISION",
            "candidate_authority": "REVIEW_ONLY",
            "automatically_acceptable": False,
            "crop_sha256": row["provenance"]["crop_sha256"],
            "usage": dict(adapter.last_usage),
        })
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "candidates.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    (args.output / "runtime.json").write_text(json.dumps({
        "fields_attempted": len(targets), "provider": "AZURE_OPENAI_VISION",
        "candidate_authority": "REVIEW_ONLY", "full_pages_sent": 0,
        "secrets_persisted": False, "evaluation_truth_loaded": False,
    }, indent=2), encoding="utf-8")
    print(json.dumps({"fields_attempted": len(targets), "full_pages_sent": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
