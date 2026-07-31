"""Registry for heterogeneous claim-page layout references."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class NormalizedRegion(BaseModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class LayoutField(BaseModel):
    field_name: str
    region: NormalizedRegion
    field_type: str
    crop_padding: float = Field(default=0.005, ge=0, le=0.1)


class LayoutAnchor(BaseModel):
    phrase: str
    required: bool
    region: NormalizedRegion | None = None


class LayoutTemplate(BaseModel):
    template_id: str
    form_family: str
    version: str
    reference_dimensions: tuple[int, int]
    anchors: list[LayoutAnchor]
    fields: list[LayoutField]
    checkbox_regions: list[NormalizedRegion] = Field(default_factory=list)
    table_regions: list[NormalizedRegion] = Field(default_factory=list)
    preprocessing_profile: str
    alignment_thresholds: dict[str, float]

    @model_validator(mode="after")
    def _requires_geometric_alignment_threshold(self) -> LayoutTemplate:
        if "minimum_inlier_ratio" not in self.alignment_thresholds:
            raise ValueError("minimum_inlier_ratio is required")
        return self


class LayoutTemplateRegistry:
    def __init__(self, root: Path = Path("config/layout_templates")) -> None:
        self.root = root

    def load_all(self) -> dict[str, LayoutTemplate]:
        return {
            path.stem: LayoutTemplate.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            )
            for path in sorted(self.root.glob("*.yaml"))
        }

    def get(self, template_id: str) -> LayoutTemplate:
        return self.load_all()[template_id]
