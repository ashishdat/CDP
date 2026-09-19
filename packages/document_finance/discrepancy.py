"""Ground-truth discrepancy ledger — no automatic Golden mutation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DiscrepancyKind(StrEnum):
    LABEL_SOURCE_CONFLICT = "LABEL_SOURCE_CONFLICT"
    PACKAGE_MAPPING_CONFLICT = "PACKAGE_MAPPING_CONFLICT"
    AMBIGUOUS_TOTAL_CHARGE_SEMANTICS = "AMBIGUOUS_TOTAL_CHARGE_SEMANTICS"
    MISSING_SOURCE_FIELD = "MISSING_SOURCE_FIELD"
    WRONG_DOCUMENT_FAMILY = "WRONG_DOCUMENT_FAMILY"
    WRONG_ROI = "WRONG_ROI"
    SOURCE_FIELD_ABSENT = "SOURCE_FIELD_ABSENT"


@dataclass
class DiscrepancyRecord:
    kind: DiscrepancyKind
    claim_id: str
    field_name: str | None = None
    label_value: str | None = None
    source_value: str | None = None
    page_index: int | None = None
    detail: str = ""
    quarantine_from_accuracy: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "claim_id": self.claim_id,
            "field_name": self.field_name,
            "label_value": self.label_value,
            "source_value": self.source_value,
            "page_index": self.page_index,
            "detail": self.detail,
            "quarantine_from_accuracy": self.quarantine_from_accuracy,
        }


@dataclass
class DiscrepancyLedger:
    records: list[DiscrepancyRecord] = field(default_factory=list)

    def add(self, record: DiscrepancyRecord) -> None:
        self.records.append(record)

    def quarantined_fields(self) -> set[tuple[str, str]]:
        return {
            (r.claim_id, str(r.field_name))
            for r in self.records
            if r.quarantine_from_accuracy and r.field_name
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.records),
            "by_kind": {
                kind.value: sum(1 for r in self.records if r.kind is kind)
                for kind in DiscrepancyKind
            },
            "records": [r.to_dict() for r in self.records],
        }


# Known disputed DOB labels from direct image review — quarantined, not mutated.
KNOWN_DOB_DISPUTES: tuple[tuple[str, str, str], ...] = (
    ("Group A/M048DJJF.003", "10/18/1916", "07/16/1946"),
    ("Group A/M048DJJF.037", "03/19/1965", "05/03/1991"),
)


def seed_known_discrepancies(ledger: DiscrepancyLedger | None = None) -> DiscrepancyLedger:
    out = ledger or DiscrepancyLedger()
    for claim_id, label, source in KNOWN_DOB_DISPUTES:
        out.add(
            DiscrepancyRecord(
                kind=DiscrepancyKind.LABEL_SOURCE_CONFLICT,
                claim_id=claim_id,
                field_name="patient_dob",
                label_value=label,
                source_value=source,
                detail="Direct image review conflicts with supplied label; quarantined.",
            )
        )
    return out
