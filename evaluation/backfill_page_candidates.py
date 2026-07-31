"""Resumable all-page candidate backfill. This module never reads ground truth."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import yaml
from PIL import Image

from packages.domain.common import ObjectRef
from packages.domain.document import Document
from packages.domain.enums import DocumentStatus, SourceFormat
from workers.field_candidates.contracts import FieldSpec, PreparedPage
from workers.field_candidates.pipeline import AllPageCandidatePipeline, CandidateStore
from workers.field_candidates.providers import default_providers
from workers.page_detection.text_extraction import TextLine


def _lines(cache: Path) -> tuple[TextLine, ...]:
    if not cache.is_file():
        return ()
    return tuple(
        TextLine(**item) for item in json.loads(cache.read_text(encoding="utf-8"))
    )


def _family_scores(
    lines: tuple[TextLine, ...], form_type: str, family_config: dict
) -> dict[str, float]:
    text = " ".join(line.text.lower() for line in lines)
    scores: dict[str, float] = {"unknown_unstructured": 0.01}
    for family, spec in family_config["families"].items():
        anchors = spec.get("required_any", [])
        matched = sum(anchor.lower() in text for anchor in anchors)
        scores[family] = matched / len(anchors) if anchors else 0.0
    if form_type == "CMS1500":
        scores["cms1500"] = max(
            scores.get("cms1500", 0.0),
            1.0 if "health insurance claim form" in text else 0.1,
        )
    if form_type == "UB04":
        scores["ub04"] = max(scores.get("ub04", 0.0), 0.9)
    return scores


def _fields(form_type: str, field_contract: dict, family_config: dict) -> list[FieldSpec]:
    result = []
    for name, spec in field_contract["forms"][form_type]["fields"].items():
        anchor_key = (
            "patient_name" if name in {"patient_first", "patient_last"}
            else "patient_address" if name.startswith("patient_") else "insured_address"
        )
        anchors = {
            anchor
            for family in family_config["families"].values()
            for anchor in family.get("fields", {}).get(anchor_key, {}).get("anchors", [])
        }
        result.append(FieldSpec(
            field_name=name,
            field_type=spec["type"],
            critical=bool(spec["critical"]),
            anchors=tuple(sorted(anchors)),
        ))
    return result


def _document(document_id: str, metadata: dict, data: bytes) -> Document:
    sha = hashlib.sha256(data).hexdigest()
    return Document(
        document_id=uuid5(NAMESPACE_URL, f"claims-idp:{document_id}"),
        tenant_id="offline-evaluation",
        source_filename=metadata["file_name"],
        detected_format=SourceFormat.TIFF,
        sha256=sha,
        page_count=0,
        status=DocumentStatus.PREPARED,
        original_object=ObjectRef(
            bucket="offline-dataset", key=metadata["file_name"], sha256=sha,
        ),
        pipeline_version="page-candidate-backfill-1",
        schema_version="1",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument("--all-pages", action="store_true", required=True)
    parser.add_argument("--overwrite-incomplete", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--inventory", type=Path,
        default=Path("evaluation_results/unstructured_inventory"),
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    field_contract = yaml.safe_load(
        Path("config/evaluation/field_contract.yaml").read_text(encoding="utf-8")
    )
    family_config = yaml.safe_load(
        Path("config/unstructured_document_families.yaml").read_text(encoding="utf-8")
    )
    pipeline = AllPageCandidatePipeline(
        default_providers(), CandidateStore(args.output)
    )
    summary = []
    for document_id, metadata in manifest.items():
        source_path = args.dataset / metadata["file_name"]
        data = source_path.read_bytes()
        document = _document(document_id, metadata, data)
        pages = []
        with Image.open(io.BytesIO(data)) as source:
            for index in range(getattr(source, "n_frames", 1)):
                source.seek(index)
                image = source.convert("RGB")
                page_number = index + 1
                cache = args.inventory / (
                    f"{source_path.name}.page-{page_number}.paddle.json"
                )
                lines = _lines(cache)
                encoded = image.tobytes()
                pages.append(PreparedPage(
                    page_number=page_number,
                    image=image.copy(),
                    image_sha256=hashlib.sha256(encoded).hexdigest(),
                    text_lines=lines,
                    family_scores=_family_scores(
                        lines, metadata["form_type"], family_config
                    ),
                ))
        candidates, outcomes = pipeline.run(
            document,
            pages,
            _fields(metadata["form_type"], field_contract, family_config),
            overwrite_incomplete=args.overwrite_incomplete,
        )
        summary.append({
            "evaluation_document_id": document_id,
            "runtime_document_id": str(document.document_id),
            "candidate_count": len(candidates),
            "routing_ready": all(item.completeness.routing_ready for item in outcomes),
            "review_required": sum(
                item.disposition == "HUMAN_REVIEW_REQUIRED" for item in outcomes
            ),
        })
        print(document_id, summary[-1])
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
