"""Append-only approved cell-label storage used only by evaluation tooling."""

from __future__ import annotations

from pathlib import Path

from packages.storage.hashing import sha256_file
from packages.table_contracts import ApprovalStatus, CellLabel, ReviewDisposition


def label_key(label: CellLabel) -> tuple:
    if label.candidate_id is not None:
        return ("candidate_id", label.candidate_id)
    return (
        label.document_id, label.page_number, label.table_type,
        label.table_index, label.row_index, label.column_name,
    )


class TableLabelStore:
    def __init__(self, path: Path, critical_columns: set[str] | None = None):
        self.path = path
        self.critical_columns = critical_columns or set()

    def read_events(self) -> list[CellLabel]:
        if not self.path.exists():
            return []
        return [
            CellLabel.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def append(self, label: CellLabel) -> None:
        events = self.read_events()
        if any(event.label_id == label.label_id for event in events):
            raise ValueError("duplicate label_id")
        same_key = [event for event in events if label_key(event) == label_key(label)]
        if any(
            event.approval_status == ApprovalStatus.APPROVED
            and label.approval_status == ApprovalStatus.APPROVED
            and event.normalized_expected_value != label.normalized_expected_value
            for event in same_key
        ):
            raise ValueError("contradictory approved label")
        requires_second = (
            label.column_name in self.critical_columns
            or label.disposition == ReviewDisposition.CORRECTED
        )
        structural = {
            ReviewDisposition.WRONG_CELL_BOUNDARY,
            ReviewDisposition.WRONG_ROW_OR_COLUMN,
            ReviewDisposition.NOT_APPLICABLE,
        }
        if label.disposition in structural:
            if label.expected_value or label.normalized_expected_value:
                raise ValueError("structural dispositions require a blank expected value")
            if not (label.review_comment or "").strip():
                raise ValueError("structural dispositions require a review comment")
        if (
            label.approval_status == ApprovalStatus.APPROVED
            and requires_second
            and (
                not label.second_reviewer_id
                or not label.second_approval_at
                or label.second_reviewer_id == label.reviewer_id
            )
        ):
            raise ValueError("critical label requires independent second approval")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(label.model_dump_json() + "\n")

    def approved(self, image_root: Path) -> list[CellLabel]:
        approved = []
        for label in self.read_events():
            if label.approval_status != ApprovalStatus.APPROVED:
                continue
            image_path = image_root / label.document_id / f"page-{label.page_number}.png"
            if not image_path.exists():
                # Current single-page evaluation convention.
                image_path = image_root / f"{label.document_id}.png"
            if not image_path.exists() or sha256_file(str(image_path)) != label.image_sha256:
                raise ValueError(f"image hash mismatch for {label.label_id}")
            approved.append(label)
        return approved
