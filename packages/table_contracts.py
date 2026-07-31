"""Auditable contracts for table-shadow candidates and approved labels."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApprovalStatus(StrEnum):
    AWAITING_HUMAN_LABEL = "AWAITING_HUMAN_LABEL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewDisposition(StrEnum):
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    BLANK_CONFIRMED = "BLANK_CONFIRMED"
    UNREADABLE = "UNREADABLE"
    WRONG_CELL_BOUNDARY = "WRONG_CELL_BOUNDARY"
    WRONG_ROW_OR_COLUMN = "WRONG_ROW_OR_COLUMN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CandidateStatus(StrEnum):
    REVIEW_ONLY = "REVIEW_ONLY"
    PRODUCTION_ELIGIBLE = "PRODUCTION_ELIGIBLE"


class CellLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_id: UUID
    candidate_id: UUID | None = None
    document_id: str
    page_number: int = Field(ge=1)
    document_family: str
    table_type: str
    table_index: int = Field(ge=0)
    row_index: int = Field(ge=0)
    column_name: str
    expected_value: str
    normalized_expected_value: str
    bbox: tuple[int, int, int, int]
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writing_type: str
    reviewer_id: str
    reviewed_at: datetime
    approval_status: ApprovalStatus
    disposition: ReviewDisposition = ReviewDisposition.APPROVED
    second_reviewer_id: str | None = None
    second_approval_at: datetime | None = None
    review_comment: str | None = None
    source: str = "HUMAN_REVIEW"

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value: tuple[int, int, int, int]):
        if value[2] <= value[0] or value[3] <= value[1]:
            raise ValueError("bbox must have positive area")
        return value


class CellCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    document_id: str
    page_number: int = Field(ge=1)
    document_family: str
    table_type: str
    table_bbox: tuple[int, int, int, int]
    table_index: int = Field(ge=0)
    row_index: int = Field(ge=0)
    column_name: str
    cell_bbox: tuple[int, int, int, int]
    raw_text: str
    normalized_value: str
    confidence: float = Field(ge=0, le=1)
    provider: str
    provider_version: str
    template_version: str
    preprocessing_profile: str
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CandidateStatus = CandidateStatus.REVIEW_ONLY
    automatically_acceptable: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    transformation_name: str = "PRESERVE_RAW"
    validation_outcome: str = "NOT_VALIDATED"
    transformation_reason: str = "No deterministic transformation applied"
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("automatically_acceptable")
    @classmethod
    def shadow_candidates_are_not_automatic(cls, value: bool, info):
        status = info.data.get("status", CandidateStatus.REVIEW_ONLY)
        if status == CandidateStatus.REVIEW_ONLY and value:
            raise ValueError("review-only candidates cannot be automatically acceptable")
        return value


class PromotionEntry(BaseModel):
    candidate_id: UUID
    field: str
    old_value: str | None
    promoted_value: str
    evidence: dict[str, Any]
    reviewer_approvals: list[dict[str, Any]]
    validation_results: dict[str, Any]
    policy_version: str
    provider_version: str
