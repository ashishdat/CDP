"""API-facing request/response models -- separate from the internal
`packages.domain.review.ReviewTask` so the wire contract can evolve
independently."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from packages.domain.review import ReviewTask


class ReviewTaskSummary(BaseModel):
    task_id: UUID
    claim_id: UUID
    field_name: str
    status: str
    created_at: datetime

    @classmethod
    def from_domain(cls, task: ReviewTask) -> ReviewTaskSummary:
        return cls(
            task_id=task.task_id,
            claim_id=task.claim_id,
            field_name=task.field_name,
            status=task.status.value,
            created_at=task.created_at,
        )


class ReviewTaskDetail(BaseModel):
    task_id: UUID
    claim_id: UUID
    document_id: UUID
    field_name: str
    page_number: int
    crop_signed_url: str | None
    page_context_signed_url: str | None
    ocr_candidates: list[str]
    vlm_candidate: str | None
    validation_errors: list[str]
    status: str

    @classmethod
    def from_domain(
        cls,
        task: ReviewTask,
        crop_signed_url: str | None,
        page_context_signed_url: str | None,
    ) -> ReviewTaskDetail:
        return cls(
            task_id=task.task_id,
            claim_id=task.claim_id,
            document_id=task.document_id,
            field_name=task.field_name,
            page_number=task.page_number,
            crop_signed_url=crop_signed_url,
            page_context_signed_url=page_context_signed_url,
            ocr_candidates=task.ocr_candidates,
            vlm_candidate=task.vlm_candidate,
            validation_errors=task.validation_errors,
            status=task.status.value,
        )


class CorrectionRequest(BaseModel):
    new_value: str
    reason: str


class RejectionRequest(BaseModel):
    reason: str


class CorrectionPromotionCandidate(BaseModel):
    field_name: str
    observed: str
    corrected: str
    occurrences: int
    distinct_documents: int
    distinct_reviewers: int
    agreement_ratio: float
    promotion_eligible: bool
