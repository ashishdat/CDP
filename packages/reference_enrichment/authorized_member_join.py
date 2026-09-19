"""Authoritative member/intake join for residual identity fields.

Accepts only an operator-authorized JSON member index. Evaluation / Golden /
agent labels are never used as lookup sources. Without an authorized file the
join abstains and the claim stays HITL — no OCR guessing on Lane C residuals.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MemberJoinHit:
    member_id: str
    patient_name: str | None
    patient_dob: str | None
    insured_name: str | None
    source: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "patient_name": self.patient_name,
            "patient_dob": self.patient_dob,
            "insured_name": self.insured_name,
            "source": self.source,
            "reasons": list(self.reasons),
        }


def _authorized_index_path() -> Path | None:
    raw = (os.environ.get("CDP_AUTHORIZED_MEMBER_INDEX") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def load_authorized_member_index(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load ``{member_id: {patient_name, patient_dob, insured_name, ...}}``."""
    target = path or _authorized_index_path()
    if target is None:
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "members" in payload:
        payload = payload["members"]
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, row in payload.items():
        mid = str(key or "").strip()
        if not mid or not isinstance(row, dict):
            continue
        out[mid] = row
    return out


def join_member_by_id(
    member_id: object,
    *,
    index: dict[str, dict[str, Any]] | None = None,
) -> MemberJoinHit | None:
    """Exact member-ID join only. Never fuzzy-matches OCR name guesses."""
    mid = str(member_id or "").strip()
    if not mid:
        return None
    table = index if index is not None else load_authorized_member_index()
    if not table:
        return None
    row = table.get(mid)
    if not isinstance(row, dict):
        # Also try digit-normalized keys.
        digits = "".join(ch for ch in mid if ch.isdigit())
        row = table.get(digits) if digits else None
    if not isinstance(row, dict):
        return None
    return MemberJoinHit(
        member_id=mid,
        patient_name=(str(row["patient_name"]).strip() if row.get("patient_name") else None),
        patient_dob=(str(row["patient_dob"]).strip() if row.get("patient_dob") else None),
        insured_name=(str(row["insured_name"]).strip() if row.get("insured_name") else None),
        source=str(row.get("source") or "AUTHORIZED_MEMBER_INDEX"),
        reasons=("EXACT_MEMBER_ID_JOIN",),
    )
