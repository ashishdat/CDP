"""Metadata-driven normalization of family-specific regional crop artifacts."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from packages.domain.common import BoundingBox, DomainModel


class RegionalArtifact(DomainModel):
    document_id: str
    page_number: int = Field(ge=1)
    family: str
    field_name: str
    crop_path: str
    source_bbox: BoundingBox
    coordinate_frame: str
    anchor_name: str | None = None
    anchor_confidence: float | None = Field(default=None, ge=0, le=1)
    crop_quality: float = Field(ge=0, le=1)
    provider_name: str
    provider_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactNormalizer:
    """Copy a crop into a stable hierarchy derived only from explicit metadata."""

    family: str

    def __init__(self, family: str) -> None:
        self.family = family

    def normalize(
        self,
        source_crop: Path,
        *,
        output_root: Path,
        document_id: str,
        document_hash: str,
        page_number: int,
        field_name: str,
        source_bbox: BoundingBox,
        coordinate_frame: str,
        crop_quality: float,
        provider_name: str,
        provider_version: str,
        anchor_name: str | None = None,
        anchor_confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RegionalArtifact:
        crop_bytes = source_crop.read_bytes()
        crop_hash = hashlib.sha256(crop_bytes).hexdigest()
        document_path_key = document_hash[:20]
        crop_path_key = crop_hash[:20]
        destination = (
            output_root / document_path_key / str(page_number) / self.family /
            field_name / f"{crop_path_key}.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source_crop, destination)
        return RegionalArtifact(
            document_id=document_id,
            page_number=page_number,
            family=self.family,
            field_name=field_name,
            crop_path=str(destination),
            source_bbox=source_bbox,
            coordinate_frame=coordinate_frame,
            anchor_name=anchor_name,
            anchor_confidence=anchor_confidence,
            crop_quality=crop_quality,
            provider_name=provider_name,
            provider_version=provider_version,
            metadata={
                **(metadata or {}),
                "document_hash": document_hash,
                "crop_hash": crop_hash,
            },
        )


class LaboratoryInvoiceArtifactNormalizer(ArtifactNormalizer):
    def __init__(self) -> None:
        super().__init__("laboratory_invoice")


class StatementArtifactNormalizer(ArtifactNormalizer):
    def __init__(self) -> None:
        super().__init__("statement")


class PsychologicalReceiptArtifactNormalizer(ArtifactNormalizer):
    def __init__(self) -> None:
        super().__init__("psychological_receipt")


class CmsAttachmentArtifactNormalizer(ArtifactNormalizer):
    def __init__(self) -> None:
        super().__init__("cms_attachment")
