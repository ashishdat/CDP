from datetime import UTC, datetime

import pytest

from evaluation.automatic_holdout import (
    AutomaticHoldoutCollector,
    HoldoutStatus,
    SealedPrediction,
    TrustedLabel,
    prediction_id,
)


def _prediction(doc="doc1", crop="crop1"):
    return SealedPrediction(
        prediction_id(doc, crop, "insured_city"), doc, crop, "CMS-1500",
        "insured_city", "ADDRESS", "HANDWRITTEN", "VALID", "NONCRITICAL",
        "SCOTTSDALE", "artifacts/prediction.json", datetime.now(UTC).isoformat(),
        "frozen-checksum",
    )


class Provider:
    def lookup(self, prediction):
        return TrustedLabel("SCOTTSDALE", "APPROVED_CORRECTION", "review-api", "1", "now", "audit-1")


def test_prediction_is_sealed_before_independent_truth(tmp_path):
    collector = AutomaticHoldoutCollector(tmp_path / "ledger.jsonl")
    item = _prediction()
    assert collector.seal(item) == HoldoutStatus.AWAITING_TRUSTED_LABEL
    assert collector.attach_truth(item, Provider()) == HoldoutStatus.EVALUATION_ELIGIBLE
    events = [line["event"] for line in map(__import__("json").loads, collector.ledger.read_text().splitlines())]
    assert events == ["PREDICTION_SEALED", "AWAITING_TRUSTED_LABEL", "CORRECTION_VERIFIED", "EVALUATION_ELIGIBLE"]


def test_deduplicates_crop_and_limits_three_fields_per_document(tmp_path):
    collector = AutomaticHoldoutCollector(tmp_path / "ledger.jsonl")
    assert collector.seal(_prediction()) == HoldoutStatus.AWAITING_TRUSTED_LABEL
    assert collector.seal(_prediction()) == HoldoutStatus.EXCLUDED_DUPLICATE
    for n in (2, 3):
        assert collector.seal(_prediction(crop=f"crop{n}")) == HoldoutStatus.AWAITING_TRUSTED_LABEL
    assert collector.seal(_prediction(crop="crop4")) == HoldoutStatus.EXCLUDED_DUPLICATE


def test_rejects_untrusted_self_label(tmp_path):
    class SelfLabel:
        def lookup(self, prediction):
            return TrustedLabel("X", "AZURE_OUTPUT", "azure", "1", "now", "x")

    collector = AutomaticHoldoutCollector(tmp_path / "ledger.jsonl")
    item = _prediction()
    collector.seal(item)
    with pytest.raises(ValueError):
        collector.attach_truth(item, SelfLabel())
