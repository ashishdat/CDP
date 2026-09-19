"""Candidate evidence store schema (lineage-complete field candidates)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class CandidateEvidenceRecord:
    claim_id: str
    package_id: str
    document_id: str
    page_number: int
    field_name: str
    crop_bbox: tuple[float, float, float, float]
    authorised_semantic_region: str
    preprocessing_variant: str
    engine: str
    model_version: str
    raw_text: str
    normalized_value: str
    model_confidence: float | None = None
    image_quality_features: dict[str, float] = field(default_factory=dict)
    registration_confidence: float | None = None
    geometry_valid: bool = False
    validation_results: list[str] = field(default_factory=list)
    reconciliation_evidence: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    acceptance_reason: str | None = None
    rejection_reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["crop_bbox"] = list(self.crop_bbox)
        return payload


class CandidateEvidenceStore:
    """In-memory store used by cascade; persist via caller to artifacts."""

    def __init__(self) -> None:
        self._rows: list[CandidateEvidenceRecord] = []

    def add(self, record: CandidateEvidenceRecord) -> CandidateEvidenceRecord:
        self._rows.append(record)
        return record

    def for_field(self, field_name: str) -> list[CandidateEvidenceRecord]:
        key = field_name.casefold()
        return [r for r in self._rows if r.field_name.casefold() == key]

    def to_list(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._rows]

    def __len__(self) -> int:
        return len(self._rows)
