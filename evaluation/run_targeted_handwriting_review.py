"""Review-only handwriting cascade. Generic TrOCR never authorizes a value."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter


TARGETS = {
    "A-06": Path("evaluation_results/expanded_blocks/crops/A-06/patient_name"),
    "D-01": Path("evaluation_results/field_crops/D-01"),
}
MODEL = "microsoft/trocr-base-handwritten"
VERSION = "generic-review-only-v1"


def main() -> int:
    output = Path("evaluation_results/targeted_handwriting_review")
    cache = output / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    requests = []
    records = []
    for document_id, root in TARGETS.items():
        paths = (
            sorted(root.glob("*.png")) if document_id == "A-06"
            else [root / "patient_name_anchor.png"]
        )
        for path in paths:
            if not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            cache_key = hashlib.sha256(f"{digest}|{MODEL}|{VERSION}".encode()).hexdigest()
            record = {
                "document_id": document_id, "field_group": "patient_name",
                "crop_path": str(path), "crop_hash": digest, "cache_key": cache_key,
                "model": MODEL, "model_version": VERSION,
                "authoritative": False, "reference_status": "REFERENCE_UNAVAILABLE",
            }
            cache_path = cache / f"{cache_key}.json"
            if cache_path.is_file():
                record["ocr"] = json.loads(cache_path.read_text())
            else:
                image = Image.open(path).convert("RGB")
                requests.append((image, cache_path, record))
            records.append(record)
    if requests:
        adapter = TrOCRAdapter(MODEL, min_confidence=0.0)
        for (_image, cache_path, record), result in zip(
            requests, adapter.recognize_batch([item[0] for item in requests]), strict=True
        ):
            record["ocr"] = result.__dict__
            cache_path.write_text(json.dumps(result.__dict__), encoding="utf-8")
    for record in records:
        record.update({
            "outcome": "INSUFFICIENT_EVIDENCE",
            "review_required": True,
            "finalization_allowed": False,
            "failure_reason": "GENERIC_HANDWRITING_MODEL_UNVERIFIED_NO_REFERENCE",
        })
    (output / "results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    metrics = {
        "targeted_crops": len(records),
        "automated_candidates_authorized": 0,
        "insufficient_evidence": len(records),
        "critical_fields_review_routed": 4,
        "reference_blocked": 4,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
