"""Canonical, Pydantic v2 domain model shared by every app/worker.

This package intentionally has no persistence, transport, or ML
dependencies — it is the vocabulary the rest of the platform speaks.
"""

from packages.domain.audit import AuditEvent
from packages.domain.claim import Claim, ServiceLine
from packages.domain.classification import PageClassification
from packages.domain.common import BoundingBox, DomainModel, ObjectRef, TenantContext
from packages.domain.document import Document, Page, PageTransform
from packages.domain.extraction import ExtractedField, ExtractionJob, FieldEvidence
from packages.domain.output import OutputArtifact
from packages.domain.review import FieldCorrection, ReviewTask
from packages.domain.routing import ModelDecision
from packages.domain.validation import ValidationResult

__all__ = [
    "AuditEvent",
    "BoundingBox",
    "Claim",
    "Document",
    "DomainModel",
    "ExtractedField",
    "ExtractionJob",
    "FieldCorrection",
    "FieldEvidence",
    "ModelDecision",
    "ObjectRef",
    "OutputArtifact",
    "Page",
    "PageClassification",
    "PageTransform",
    "ReviewTask",
    "ServiceLine",
    "TenantContext",
    "ValidationResult",
]
