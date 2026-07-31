"""Normalize explicit attachment artifacts without deriving identity from filenames."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml
from PIL import Image

from packages.domain.common import BoundingBox
from workers.field_candidates.artifacts import (
    CmsAttachmentArtifactNormalizer,
    LaboratoryInvoiceArtifactNormalizer,
    PsychologicalReceiptArtifactNormalizer,
    StatementArtifactNormalizer,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    normalizers = {
        "laboratory_invoice": LaboratoryInvoiceArtifactNormalizer,
        "statement": StatementArtifactNormalizer,
        "psychological_receipt": PsychologicalReceiptArtifactNormalizer,
        "cms_attachment": CmsAttachmentArtifactNormalizer,
    }
    if manifest["family"] not in normalizers:
        raise ValueError(f"unsupported attachment family: {manifest['family']}")
    normalizer = normalizers[manifest["family"]]()
    artifacts = []
    failures = []
    document_hashes: dict[str, str] = {}
    for document_id in {item["document_id"] for item in manifest["artifacts"]}:
        digest = hashlib.sha256()
        for item in sorted(
            (item for item in manifest["artifacts"] if item["document_id"] == document_id),
            key=lambda item: (item["page_number"], item["field_name"]),
        ):
            source = Path(item["source_crop"])
            if source.is_file():
                digest.update(source.read_bytes())
        document_hashes[document_id] = digest.hexdigest()
    for entry in manifest["artifacts"]:
        source = Path(entry["source_crop"])
        if not source.is_file():
            failures.append({**entry, "failure_reason": "SOURCE_CROP_MISSING"})
            continue
        with Image.open(source) as image:
            width, height = image.size
        document_hash = document_hashes[entry["document_id"]]
        artifact = normalizer.normalize(
            source,
            output_root=args.output / "crops",
            document_id=entry["document_id"],
            document_hash=document_hash,
            page_number=entry["page_number"],
            field_name=entry["field_name"],
            source_bbox=BoundingBox(
                x0=0, y0=0, x1=width, y1=height,
                image_width=width, image_height=height,
            ),
            coordinate_frame="LOCAL_CROP",
            crop_quality=entry["crop_quality"],
            provider_name=manifest["provider_name"],
            provider_version=manifest["provider_version"],
            metadata={
                "source_manifest": str(args.manifest),
                "source_page_bbox_status": "NOT_AVAILABLE_FROM_LEGACY_EXTRACTOR",
            },
        )
        artifacts.append(artifact.model_dump(mode="json"))
    args.output.mkdir(parents=True, exist_ok=True)
    completeness = {
        "family": manifest["family"],
        "declared_artifacts": len(manifest["artifacts"]),
        "normalized_artifacts": len(artifacts),
        "failures": len(failures),
        "normalization_completeness": (
            len(artifacts) / len(manifest["artifacts"])
            if manifest["artifacts"] else 0.0
        ),
        "routing_metadata_source": "EXPLICIT_MANIFEST",
        "legacy_source_page_bbox_complete": False,
    }
    (args.output / "artifacts.json").write_text(
        json.dumps(artifacts, indent=2), encoding="utf-8"
    )
    (args.output / "failures.json").write_text(
        json.dumps(failures, indent=2), encoding="utf-8"
    )
    (args.output / "metrics.json").write_text(
        json.dumps(completeness, indent=2), encoding="utf-8"
    )
    print(json.dumps(completeness, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
