"""Append-only two-step human verification for insufficient-evidence fields."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from packages.handwriting_dataset import AppendOnlyHandwritingDataset


class VerifiedClosureWorkflow:
    def __init__(self, audit_path: Path, training_path: Path) -> None:
        self.audit_path = audit_path
        self.training = AppendOnlyHandwritingDataset(training_path)

    def submit(
        self, task: dict, *, corrected_value: str, reviewer: str, reason: str
    ) -> dict:
        if task["status"] != "OPEN":
            raise ValueError("task is not open")
        value = corrected_value.strip()
        if not value or not all(ch.isalpha() or ch in " '-." for ch in value):
            raise ValueError("name correction failed deterministic validation")
        updated = {
            **task, "status": "PENDING_SECOND_APPROVAL",
            "correction": value, "reviewer": reviewer, "review_reason": reason,
            "reviewed_at": datetime.now(UTC).isoformat(),
        }
        self._audit(updated, "CORRECTION_SUBMITTED", reviewer)
        return updated

    def approve(self, task: dict, *, approver: str, validator: str) -> dict:
        if task["status"] != "PENDING_SECOND_APPROVAL":
            raise ValueError("task does not have a pending correction")
        if approver == task["reviewer"]:
            raise ValueError("second approval requires role separation")
        crop_path = Path(task["primary_crop"])
        self.training.approve(
            crop=crop_path.read_bytes(),
            crop_reference=str(crop_path),
            field_name=task["field_name"],
            ocr_value=task["ocr_candidates"][0] if task["ocr_candidates"] else None,
            corrected_value=task["correction"],
            reviewer=task["reviewer"],
            validator=validator,
            approved_by=approver,
            document_family=task["document_family"],
        )
        updated = {
            **task, "status": "VERIFIED_BY_HUMAN", "approved_by": approver,
            "validated_by": validator, "approved_at": datetime.now(UTC).isoformat(),
            "claim_revalidation": "REQUIRED", "finalization_allowed": True,
        }
        self._audit(updated, "VERIFIED_BY_HUMAN", approver)
        return updated

    def _audit(self, task: dict, event: str, actor: str) -> None:
        payload = {
            "event": event, "task_id": task["task_id"], "document_id": task["document_id"],
            "field_name": task["field_name"], "actor": actor,
            "timestamp": datetime.now(UTC).isoformat(),
            "correction_hash": hashlib.sha256(
                str(task.get("correction", "")).encode()
            ).hexdigest(),
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")

