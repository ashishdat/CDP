"""Versioned CMS-1500/UB-04 template registry (Phase 2).

Templates are data (`config/templates/*.yaml`), loaded by
`TemplateRegistry`. See docs/CONFIGURATION_GUIDE.md for the field schema.
"""

from packages.templates.models import (
    AnchorDefinition,
    FieldRegion,
    ReferenceDimensions,
    ServiceLineTableRegion,
    Template,
)
from packages.templates.registry import TemplateNotFoundError, TemplateRegistry

__all__ = [
    "AnchorDefinition",
    "FieldRegion",
    "ReferenceDimensions",
    "ServiceLineTableRegion",
    "Template",
    "TemplateNotFoundError",
    "TemplateRegistry",
]
