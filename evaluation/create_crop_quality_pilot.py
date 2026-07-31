"""Create a truth-free 30-cell pilot after crop-quality validation."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from PIL import Image

from workers.table_extraction.crop_quality import (
    CropQualityStatus,
    image_hash,
    validate_crop,
)
from workers.table_extraction.semantic_cells import extract_semantic_rows
from workers.table_extraction.template_registration import (
    persist_registration,
    register_page,
)

QUARANTINE = Path(
    "evaluation_data/table_labels/quarantine/table-shadow-v2/candidate_results"
)
OUTPUT = Path("evaluation_results/table_crop_quality_pilot")
TARGETS = {"CMS1500": 10, "UB04": 10, "laboratory_invoice": 5, "statement": 5}
PILOT_VERSION = "crop-pilot-v3"


def _translated(path: str) -> Path:
    source = Path(path)
    parts = source.parts
    try:
        index = parts.index("table_shadow_v2")
    except ValueError:
        return source
    return QUARANTINE.joinpath(*parts[index + 1 :])


def _persist_cell(
    crop: Image.Image,
    context: Image.Image,
    directory: Path,
    identity: str,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(identity.encode()).hexdigest()
    crop_path = directory / f"{digest}.png"
    context_path = directory / f"{digest}.row.png"
    crop.save(crop_path)
    context.save(context_path)
    return crop_path, context_path


def _safe_interior_bbox(
    page: Image.Image, bbox: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Trim detected border rules, with a two-pixel minimum inset."""
    x0, y0, x1, y1 = bbox
    gray = np.asarray(page.crop(bbox).convert("L"))
    ink = gray < 120
    width, height = gray.shape[1], gray.shape[0]
    vertical = ink.mean(axis=0)
    horizontal = ink.mean(axis=1)
    left_lines = np.where(vertical[: min(15, width)] > 0.6)[0]
    right_lines = np.where(vertical[max(0, width - 15) :] > 0.6)[0]
    top_lines = np.where(horizontal[: min(12, height)] > 0.6)[0]
    bottom_lines = np.where(horizontal[max(0, height - 12) :] > 0.6)[0]
    left = max(2, int(left_lines.max()) + 2 if left_lines.size else 2)
    right = min(
        width - 2,
        max(0, width - 15) + int(right_lines.min()) - 2
        if right_lines.size
        else width - 2,
    )
    top = max(2, int(top_lines.max()) + 2 if top_lines.size else 2)
    bottom = min(
        height - 2,
        max(0, height - 12) + int(bottom_lines.min()) - 2
        if bottom_lines.size
        else height - 2,
    )
    if right <= left or bottom <= top:
        return (x0 + 2, y0 + 2, x1 - 2, y1 - 2)
    return (x0 + left, y0 + top, x0 + right, y0 + bottom)


def _fixed_candidates(
    family: str, documents: dict[str, dict], rejected: list[dict]
) -> list[dict]:
    result = []
    for document_id, source in sorted(documents.items()):
        page_path = _translated(source["provenance"]["source_image"])
        with Image.open(page_path) as opened:
            original = opened.convert("RGB")
        registration = register_page(original, family)
        document_root = OUTPUT / "registrations" / document_id
        registration_paths = persist_registration(registration, family, document_root)
        original_path = document_root / "original_page.png"
        shutil.copy2(page_path, original_path)
        for row in extract_semantic_rows(registration.registered_page, family):
            if row["row_status"] != "ACTIVE":
                rejected.append(
                    {
                        "document_id": document_id,
                        "family": family,
                        "service_line_number": row["service_line_number"],
                        "quality_status": (
                            "UNUSED_ROW"
                            if row["row_status"] == "UNUSED"
                            else "AMBIGUOUS_GEOMETRY"
                        ),
                    }
                )
                continue
            context = registration.registered_page.crop(row["row_bbox"])
            for cell in row["cells"]:
                identity = (
                    f"{PILOT_VERSION}:{document_id}:{cell.service_line_number}:"
                    f"{cell.semantic_field_name}:{cell.registered_bbox}"
                )
                crop_path, context_path = _persist_cell(
                    cell.crop, context, OUTPUT / "crops" / document_id, identity
                )
                digest = image_hash(crop_path)
                status, reasons = validate_crop(
                    crop_path,
                    cell.registered_bbox,
                    registration.registered_page.size,
                    expected_hash=digest,
                    registration_status=registration.status,
                    row_status=row["row_status"],
                )
                record = {
                    "candidate_id": str(uuid5(NAMESPACE_URL, identity)),
                    "document_id": document_id,
                    "page_number": 1,
                    "document_family": family,
                    "form_version": cell.form_version,
                    "form_locator": cell.form_locator,
                    "service_line_number": cell.service_line_number,
                    "semantic_field_name": cell.semantic_field_name,
                    "data_type": cell.data_type,
                    "validation_policy": cell.validation_policy,
                    "template_bbox": cell.template_bbox,
                    "registered_bbox": cell.registered_bbox,
                    "crop_path": str(crop_path),
                    "crop_sha256": digest,
                    "row_context_path": str(context_path),
                    "original_page": str(original_path),
                    **registration_paths,
                    "transformation_matrix": registration.matrix,
                    "registration_residual_error": registration.residual_error,
                    "registration_status": registration.status,
                    "row_status": row["row_status"],
                    "row_evidence": row["row_evidence"],
                    "crop_quality_status": status.value,
                    "crop_quality_reasons": reasons,
                    "ocr_suggestion": "",
                    "ocr_suggestion_authority": "UNVERIFIED_OCR_SUGGESTION",
                    "automatically_acceptable": False,
                }
                if status is CropQualityStatus.VALID_SINGLE_CELL:
                    result.append(record)
                else:
                    rejected.append(record)
    return result


def _variable_candidates(
    family: str, candidates: list[dict], rejected: list[dict]
) -> list[dict]:
    result = []
    for candidate in candidates:
        if candidate["document_family"] != family:
            continue
        field = candidate["column_name"]
        if field.startswith("column_"):
            rejected.append({**candidate, "quality_status": "AMBIGUOUS_GEOMETRY"})
            continue
        source_path = _translated(candidate["provenance"]["source_image"])
        with Image.open(source_path) as opened:
            page = opened.convert("RGB")
        x0, y0, x1, y1 = candidate["cell_bbox"]
        registered_bbox = _safe_interior_bbox(page, (x0, y0, x1, y1))
        identity = (
            f"{PILOT_VERSION}:{candidate['candidate_id']}:{registered_bbox}"
        )
        crop, context = (
            page.crop(registered_bbox),
            page.crop(tuple(candidate["table_bbox"])),
        )
        crop_path, context_path = _persist_cell(
            crop,
            context,
            OUTPUT / "crops" / candidate["document_id"],
            identity,
        )
        status, reasons = validate_crop(
            crop_path,
            registered_bbox,
            page.size,
            expected_hash=image_hash(crop_path),
            registration_status="REGISTERED",
            row_status="ACTIVE",
        )
        if status is not CropQualityStatus.VALID_SINGLE_CELL:
            rejected.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "quality_status": status.value,
                    "reasons": reasons,
                }
            )
            continue
        field_types = {
            "service_date": "date",
            "fee_for_service": "currency",
            "cpt_code": "code",
            "test_description": "text",
        }
        result.append(
            {
                "candidate_id": candidate["candidate_id"],
                "document_id": candidate["document_id"],
                "page_number": candidate["page_number"],
                "document_family": family,
                "form_version": candidate["template_version"],
                "form_locator": candidate["column_name"].upper(),
                "service_line_number": candidate["row_index"] + 1,
                "semantic_field_name": field,
                "data_type": field_types.get(field, "text"),
                "validation_policy": candidate["validation_outcome"],
                "template_bbox": candidate["cell_bbox"],
                "registered_bbox": registered_bbox,
                "crop_path": str(crop_path),
                "crop_sha256": image_hash(crop_path),
                "row_context_path": str(context_path),
                "original_page": str(
                    source_path
                ),
                "canonical_template": None,
                "registered_page": str(
                    _translated(candidate["provenance"]["aligned_page"])
                ),
                "registration_overlay": str(
                    _translated(candidate["provenance"]["grid_overlay"])
                ),
                "registration_evidence": None,
                "transformation_matrix": candidate["provenance"]["transform_matrix"],
                "registration_residual_error": None,
                "registration_status": "ANCHOR_REGISTERED",
                "row_status": "ACTIVE",
                "row_evidence": [],
                "crop_quality_status": status.value,
                "crop_quality_reasons": [],
                "ocr_suggestion": candidate["raw_text"],
                "ocr_suggestion_authority": "UNVERIFIED_OCR_SUGGESTION",
                "automatically_acceptable": False,
            }
        )
    return result


def _balanced(records: list[dict], count: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[record["semantic_field_name"]].append(record)
    selected = []
    while len(selected) < count and any(groups.values()):
        for field in sorted(groups):
            if groups[field] and len(selected) < count:
                selected.append(groups[field].pop(0))
    return selected


def create() -> dict:
    if OUTPUT.exists():
        raise FileExistsError(f"{OUTPUT} already exists; pilot output is immutable")
    OUTPUT.mkdir(parents=True)
    candidates_path = QUARANTINE / "candidates.jsonl"
    candidates = [
        json.loads(line)
        for line in candidates_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    documents: dict[str, dict[str, dict]] = defaultdict(dict)
    for candidate in candidates:
        documents[candidate["document_family"]].setdefault(
            candidate["document_id"], candidate
        )
    rejected: list[dict] = []
    pools = {
        "CMS1500": _fixed_candidates("CMS1500", documents["CMS1500"], rejected),
        "UB04": _fixed_candidates("UB04", documents["UB04"], rejected),
        "laboratory_invoice": _variable_candidates(
            "laboratory_invoice", candidates, rejected
        ),
        "statement": _variable_candidates("statement", candidates, rejected),
    }
    selected = []
    for family, target in TARGETS.items():
        family_selected = _balanced(pools[family], target)
        if len(family_selected) != target:
            raise RuntimeError(
                f"{family} has {len(family_selected)}/{target} valid pilot crops"
            )
        selected.extend(family_selected)
    with (OUTPUT / "pilot_manifest.jsonl").open("w", encoding="utf-8") as handle:
        for item in selected:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    (OUTPUT / "rejected.json").write_text(
        json.dumps(rejected, indent=2, default=str), encoding="utf-8"
    )
    metrics = {
        "pilot_crops_generated": len(selected),
        "by_family": {
            family: sum(item["document_family"] == family for item in selected)
            for family in TARGETS
        },
        "rejected_before_manifest": len(rejected),
        "evaluation_truth_loaded": False,
        "ocr_accuracy_evaluated": False,
    }
    (OUTPUT / "generation_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    return metrics


def main() -> int:
    print(json.dumps(create(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
