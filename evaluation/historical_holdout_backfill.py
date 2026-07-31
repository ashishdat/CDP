"""Historical holdout enrollment with strict overlap and lineage checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from evaluation.automatic_holdout import (
    AutomaticHoldoutCollector,
    HoldoutStatus,
    LabelStrength,
    SealedPrediction,
    TrustedLabel,
)
from packages.downstream_claims_connector import FinalizedClaimsConnector

SUPPORTED_FAMILIES = {"CMS-1500", "CMS1500", "UB-04", "UB04", "ATTACHMENT"}


@dataclass(frozen=True)
class HistoricalDocument:
    document_hash: str
    perceptual_hashes: tuple[str, ...]
    claim_identifier: str
    document_identifier: str
    document_family: str


class FrozenInference(Protocol):
    def unresolved_predictions(self, document: HistoricalDocument) -> list[SealedPrediction]: ...


@dataclass(frozen=True)
class _StaticLabelProvider:
    label: TrustedLabel

    def lookup(self, _prediction: SealedPrediction) -> TrustedLabel:
        return self.label


def hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


class BackfillCoordinator:
    def __init__(self, collector: AutomaticHoldoutCollector,
                 downstream: FinalizedClaimsConnector, inference: FrozenInference,
                 *, excluded_hashes: set[str], excluded_perceptual_hashes: set[str],
                 perceptual_distance: int = 2) -> None:
        self.collector, self.downstream, self.inference = collector, downstream, inference
        self.excluded_hashes = excluded_hashes
        self.excluded_perceptual_hashes = excluded_perceptual_hashes
        self.perceptual_distance = perceptual_distance

    def _overlaps(self, document: HistoricalDocument) -> bool:
        if document.document_hash in self.excluded_hashes:
            return True
        return any(
            hamming_distance(candidate, excluded) <= self.perceptual_distance
            for candidate in document.perceptual_hashes
            for excluded in self.excluded_perceptual_hashes
        )

    def process(self, document: HistoricalDocument) -> dict:
        if document.document_family not in SUPPORTED_FAMILIES:
            return {"status": "EXCLUDED_UNSUPPORTED_FAMILY", "sealed": 0, "eligible": 0}
        if self._overlaps(document):
            return {"status": "EXCLUDED_DEVELOPMENT_OVERLAP", "sealed": 0, "eligible": 0}
        # Inference and sealing happen before the downstream connector is queried.
        predictions = self.inference.unresolved_predictions(document)
        sealed = [item for item in predictions if self.collector.seal(item) == HoldoutStatus.AWAITING_TRUSTED_LABEL]
        downstream = self.downstream.finalized_fields(document.claim_identifier)
        by_field = {row.field_name: row for row in downstream if row.document_identifier in {None, document.document_identifier}}
        eligible = rejected_lineage = 0
        for prediction in sealed:
            row = by_field.get(prediction.field_name)
            if row is None:
                continue
            if row.derived_from_cdp or row.lineage_origin.upper() in {"CDP", "AZURE", "OCR_CONSENSUS"}:
                rejected_lineage += 1
                continue

            provider = _StaticLabelProvider(TrustedLabel(
                row.value, "DOWNSTREAM_ACCEPTED", row.source_system,
                row.source_record_version, row.finalized_at, row.audit_reference,
                LabelStrength.TIER_B, False,
            ))
            eligible += self.collector.attach_truth(prediction, provider) == HoldoutStatus.EVALUATION_ELIGIBLE
        return {
            "status": "PROCESSED", "sealed": len(sealed), "eligible": eligible,
            "rejected_lineage": rejected_lineage,
        }
