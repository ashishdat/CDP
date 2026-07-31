"""Repository over the review_tasks table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.human_review_api.db.mappers import orm_to_task, task_to_orm
from apps.human_review_api.db.models import ReviewTaskORM
from packages.domain.enums import ReviewTaskStatus
from packages.domain.review import ReviewTask


class ReviewTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: ReviewTask) -> None:
        self._session.add(task_to_orm(task))
        self._session.flush()

    def get(self, task_id: UUID) -> ReviewTask | None:
        row = self._session.get(ReviewTaskORM, task_id)
        return orm_to_task(row) if row else None

    def list_open(self, limit: int = 100) -> list[ReviewTask]:
        stmt = (
            select(ReviewTaskORM)
            .where(ReviewTaskORM.status == ReviewTaskStatus.OPEN.value)
            .order_by(ReviewTaskORM.created_at)
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_task(r) for r in rows]

    def list_for_claim(self, claim_id: UUID) -> list[ReviewTask]:
        stmt = select(ReviewTaskORM).where(ReviewTaskORM.claim_id == claim_id)
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_task(r) for r in rows]

    def save(self, task: ReviewTask) -> None:
        row = self._session.get(ReviewTaskORM, task.task_id)
        if row is None:
            raise ValueError(f"review task {task.task_id} not found")
        row.status = task.status.value
        row.assigned_to = task.assigned_to
        if task.correction is not None:
            row.correction_reviewer = task.correction.reviewer
            row.correction_corrected_at = task.correction.corrected_at
            row.correction_previous_value = task.correction.previous_value
            row.correction_new_value = task.correction.new_value
            row.correction_reason = task.correction.reason
        self._session.flush()
