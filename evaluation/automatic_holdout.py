"""Append-only collection of independently labeled Azure holdout examples.

Predictions are sealed before a trusted-label provider is queried.  Evaluation
truth is deliberately absent from the inference-side API.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class HoldoutStatus(StrEnum):
    PREDICTION_SEALED = "PREDICTION_SEALED"
    AWAITING_TRUSTED_LABEL = "AWAITING_TRUSTED_LABEL"
    REFERENCE_VERIFIED = "REFERENCE_VERIFIED"
    DOWNSTREAM_VERIFIED = "DOWNSTREAM_VERIFIED"
    CORRECTION_VERIFIED = "CORRECTION_VERIFIED"
    EVALUATION_ELIGIBLE = "EVALUATION_ELIGIBLE"
    EXCLUDED_DUPLICATE = "EXCLUDED_DUPLICATE"
    EXCLUDED_NO_INDEPENDENT_TRUTH = "EXCLUDED_NO_INDEPENDENT_TRUTH"


class LabelStrength(StrEnum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    REJECTED = "REJECTED"


TRUSTED_STATUSES = {
    HoldoutStatus.REFERENCE_VERIFIED,
    HoldoutStatus.DOWNSTREAM_VERIFIED,
    HoldoutStatus.CORRECTION_VERIFIED,
}


@dataclass(frozen=True)
class TrustedLabel:
    value: str
    source_type: str
    source_system: str
    source_version: str
    verified_at: str
    audit_reference: str
    label_strength: str = LabelStrength.TIER_A
    derived_from_cdp: bool = False


@dataclass(frozen=True)
class SealedPrediction:
    prediction_id: str
    document_hash: str
    crop_hash: str
    document_family: str
    field_name: str
    field_type: str
    writing_type: str
    crop_condition: str
    criticality: str
    predicted_value: str | None
    prediction_artifact: str
    sealed_at: str
    config_checksum: str
    status: str = HoldoutStatus.PREDICTION_SEALED
    trusted_label: TrustedLabel | None = None


class TrustedLabelProvider(Protocol):
    def lookup(self, prediction: SealedPrediction) -> TrustedLabel | None: ...


def prediction_id(document_hash: str, crop_hash: str, field_name: str) -> str:
    payload = f"{document_hash}:{crop_hash}:{field_name}".encode()
    return hashlib.sha256(payload).hexdigest()


class AutomaticHoldoutCollector:
    """Deterministic collector with document-level and crop-level deduplication."""

    def __init__(self, ledger: Path, *, maximum_fields_per_document: int = 3) -> None:
        self.ledger = ledger
        self.maximum_fields_per_document = maximum_fields_per_document

    def _rows(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        return [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines() if line]

    def _append(self, event: dict) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    def seal(self, item: SealedPrediction) -> HoldoutStatus:
        rows = self._rows()
        accepted = [row for row in rows if row.get("event") == "PREDICTION_SEALED"]
        duplicate = any(
            row["prediction"]["crop_hash"] == item.crop_hash
            or row["prediction"]["prediction_id"] == item.prediction_id
            for row in accepted
        )
        document_count = sum(row["prediction"]["document_hash"] == item.document_hash for row in accepted)
        if duplicate or document_count >= self.maximum_fields_per_document:
            self._append({"event": HoldoutStatus.EXCLUDED_DUPLICATE, "prediction_id": item.prediction_id})
            return HoldoutStatus.EXCLUDED_DUPLICATE
        self._append({"event": "PREDICTION_SEALED", "prediction": asdict(item)})
        self._append({"event": HoldoutStatus.AWAITING_TRUSTED_LABEL, "prediction_id": item.prediction_id})
        return HoldoutStatus.AWAITING_TRUSTED_LABEL

    def attach_truth(self, item: SealedPrediction, provider: TrustedLabelProvider) -> HoldoutStatus:
        # This method is intentionally separate from seal(), making prediction-before-label auditable.
        label = provider.lookup(item)
        if label is None:
            self._append({"event": HoldoutStatus.EXCLUDED_NO_INDEPENDENT_TRUTH, "prediction_id": item.prediction_id})
            return HoldoutStatus.EXCLUDED_NO_INDEPENDENT_TRUTH
        source_status = {
            "AUTHORIZED_REFERENCE": HoldoutStatus.REFERENCE_VERIFIED,
            "DOWNSTREAM_ACCEPTED": HoldoutStatus.DOWNSTREAM_VERIFIED,
            "APPROVED_CORRECTION": HoldoutStatus.CORRECTION_VERIFIED,
        }.get(label.source_type)
        official_strength = label.label_strength in {LabelStrength.TIER_A, LabelStrength.TIER_B}
        if source_status not in TRUSTED_STATUSES or not official_strength or label.derived_from_cdp:
            raise ValueError("label source is not authorized for certification")
        verified = replace(item, status=source_status, trusted_label=label)
        self._append({"event": source_status, "prediction": asdict(verified)})
        self._append({"event": HoldoutStatus.EVALUATION_ELIGIBLE, "prediction_id": item.prediction_id})
        return HoldoutStatus.EVALUATION_ELIGIBLE

    def summary(self) -> dict:
        rows = self._rows()
        events: dict[str, int] = {}
        documents: set[str] = set()
        for row in rows:
            events[str(row["event"])] = events.get(str(row["event"]), 0) + 1
            prediction = row.get("prediction")
            if prediction:
                documents.add(prediction["document_hash"])
        eligible = events.get(HoldoutStatus.EVALUATION_ELIGIBLE, 0)
        return {
            "eligible_fields": eligible,
            "unique_documents_seen": len(documents),
            "target_fields": 300,
            "target_documents": 100,
            "collection_complete": eligible >= 300 and len(documents) >= 100,
            "events": events,
        }
