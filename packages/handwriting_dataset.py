"""Controlled, append-only workflow for approved handwriting labels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApprovedHandwritingLabel:
    crop_reference: str
    crop_sha256: str
    field_name: str
    ocr_value: str | None
    corrected_value: str
    reviewer: str
    validator: str
    approved_by: str
    document_family: str
    quality_status: str = "approved"


class AppendOnlyHandwritingDataset:
    def __init__(self, path: Path) -> None:
        self.path = path

    def approve(
        self,
        *,
        crop: bytes,
        crop_reference: str,
        field_name: str,
        ocr_value: str | None,
        corrected_value: str,
        reviewer: str,
        validator: str,
        approved_by: str,
        document_family: str,
    ) -> ApprovedHandwritingLabel:
        if not corrected_value.strip():
            raise ValueError("corrected value cannot be empty")
        if len({reviewer, validator, approved_by}) < 2:
            raise ValueError("approval requires separation of reviewer and approver roles")
        label = ApprovedHandwritingLabel(
            crop_reference=crop_reference,
            crop_sha256=hashlib.sha256(crop).hexdigest(),
            field_name=field_name,
            ocr_value=ocr_value,
            corrected_value=corrected_value.strip(),
            reviewer=reviewer,
            validator=validator,
            approved_by=approved_by,
            document_family=document_family,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(label)) + "\n")
        return label

    def training_manifest(
        self, *, minimum_examples: int = 100, minimum_families: int = 3
    ) -> list[dict]:
        rows = [
            json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ] if self.path.is_file() else []
        unique_crops = {row["crop_sha256"] for row in rows}
        families = {row["document_family"] for row in rows}
        if len(unique_crops) < minimum_examples or len(families) < minimum_families:
            raise ValueError(
                "insufficient diverse approved labels for fine-tuning: "
                f"{len(unique_crops)} crops, {len(families)} families"
            )
        return rows
