"""Template domain model: versioned CMS-1500/UB-04 form definitions.

Pure data -- no OpenCV/OCR dependency here. `workers/page_detection` and
`workers/standard_form_extraction` consume these; `packages/templates`
only knows how to load and validate them.
"""

from __future__ import annotations

from pydantic import Field

from packages.domain.common import DomainModel
from packages.domain.enums import ClaimFormType


class ReferenceDimensions(DomainModel):
    width_px: int
    height_px: int


class AnchorDefinition(DomainModel):
    """A phrase that must appear (via OCR) near the top of a genuine page
    of this form. `region` is optional -- when set, the phrase is only
    searched for within that area (cheaper, fewer false positives)."""

    phrase: str
    region: FieldRegion | None = None
    required: bool = True


class FieldRegion(DomainModel):
    """A named field's location on the reference-dimensions image, in
    pixels. `packages.domain.common.BoundingBox` is the *evidence* shape
    (tied to one extracted field on one real page); this is the *template*
    shape (tied to the reference image every real page is aligned to)."""

    field_name: str
    x0: int
    y0: int
    x1: int
    y1: int
    field_type: str = "text"  # text | date | code | currency | checkbox | npi | tax_id
    postprocessor: str | None = None
    padding_px: int = Field(default=4, ge=0)


class ServiceLineTableRegion(DomainModel):
    """A repeating row/column grid (CMS-1500 box 24, UB-04 42-49)."""

    table_x0: int
    table_y0: int
    table_x1: int
    table_y1: int
    max_rows: int
    row_height_px: int
    columns: list[FieldRegion]  # x0/x1 are column bounds; y0/y1 unused (=0)


class Template(DomainModel):
    template_id: str
    version: str
    form_type: ClaimFormType
    reference_dimensions: ReferenceDimensions
    anchor_definitions: list[AnchorDefinition]
    field_regions: list[FieldRegion]
    service_line_region: ServiceLineTableRegion | None = None
    required_fields: list[str] = Field(default_factory=list)
    validation_profile: str = "default"
    # Optional path (relative to this template's YAML file) to a real,
    # operator-supplied clean/representative scan of the printed form. When
    # present, it unlocks real OpenCV alignment (grid-signature +
    # ORB/homography) instead of the anchor-phrase-only / rescale-only
    # fallback -- see packages.templates.registry.TemplateRegistry.
    # load_reference_image. Never commit a real scan here: PHI-bearing
    # dataset images must stay out of source control (docs/
    # DATASET_FINDINGS.md) -- operators supply their own at deploy time
    # under the gitignored config/templates/reference_images/ directory.
    reference_image_path: str | None = None

    def field_region(self, field_name: str) -> FieldRegion | None:
        return next((f for f in self.field_regions if f.field_name == field_name), None)
