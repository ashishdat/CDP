"""Build leak-resistant handwriting datasets from independently trusted labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

AUTHORIZED_LABEL_SOURCES = {
    "AUTHORIZED_REFERENCE", "APPROVED_CORRECTION", "DOWNSTREAM_ACCEPTED",
}


def split_for_document(document_hash: str) -> str:
    bucket = int(hashlib.sha256(document_hash.encode()).hexdigest()[:8], 16) % 100
    if bucket < 70:
        return "TRAIN"
    if bucket < 85:
        return "VALIDATION"
    return "HOLDOUT"


def build_training_manifest(rows: list[dict], *, minimum_samples: int = 100) -> dict:
    accepted: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    conflicts: set[tuple[str, str]] = set()
    labels: dict[tuple[str, str], str] = {}
    for row in rows:
        if row.get("label_source") not in AUTHORIZED_LABEL_SOURCES:
            continue
        key = (row["document_hash"], row["field_name"])
        value = row["trusted_value"]
        if key in labels and labels[key] != value:
            conflicts.add(key)
        labels[key] = value
    for row in rows:
        key = (row["document_hash"], row["field_name"])
        duplicate_key = (*key, row["crop_hash"])
        if (
            row.get("label_source") not in AUTHORIZED_LABEL_SOURCES
            or key in conflicts
            or duplicate_key in seen
        ):
            continue
        seen.add(duplicate_key)
        accepted.append({**row, "dataset_split": split_for_document(row["document_hash"])})
    families = {row["document_family"] for row in accepted}
    return {
        "samples": accepted,
        "metrics": {
            "approved_unique_samples": len(accepted),
            "document_families": len(families),
            "conflicting_document_fields": len(conflicts),
            "fine_tuning_enabled": len(accepted) >= minimum_samples and len(families) >= 3,
            "split_unit": "DOCUMENT",
        },
    }


def write_manifest(rows_path: Path, output: Path, *, minimum_samples: int = 100) -> None:
    result = build_training_manifest(json.loads(rows_path.read_text()), minimum_samples=minimum_samples)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
