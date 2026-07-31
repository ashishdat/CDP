from datetime import UTC, datetime

from evaluation.automatic_holdout import AutomaticHoldoutCollector, SealedPrediction, prediction_id
from evaluation.historical_holdout_backfill import BackfillCoordinator, HistoricalDocument
from packages.downstream_claims_connector import DownstreamFieldValue

DOC = HistoricalDocument("sha-new", ("01234567",), "claim-1", "doc-1", "CMS-1500")


class Inference:
    def unresolved_predictions(self, document):
        return [SealedPrediction(
            prediction_id(document.document_hash, "crop", "insured_city"), document.document_hash,
            "crop", document.document_family, "insured_city", "ADDRESS", "HANDWRITTEN",
            "VALID", "NONCRITICAL", "SCOTTSDALE", "prediction.json",
            datetime.now(UTC).isoformat(), "frozen",
        )]


class Downstream:
    derived = False
    def readiness(self): return {"status": "READY"}
    def finalized_fields(self, claim_identifier):
        return [DownstreamFieldValue(
            claim_identifier, "doc-1", "insured_city", "SCOTTSDALE", "now", "claims-db",
            "42", "ADJUDICATION", self.derived, "audit-42",
        )]


def test_backfill_seals_before_independent_tier_b_enrollment(tmp_path):
    collector = AutomaticHoldoutCollector(tmp_path / "ledger.jsonl")
    result = BackfillCoordinator(collector, Downstream(), Inference(), excluded_hashes=set(), excluded_perceptual_hashes=set()).process(DOC)
    assert result == {"status": "PROCESSED", "sealed": 1, "eligible": 1, "rejected_lineage": 0}


def test_cdp_derived_downstream_value_is_rejected(tmp_path):
    source = Downstream(); source.derived = True
    result = BackfillCoordinator(AutomaticHoldoutCollector(tmp_path / "l.jsonl"), source, Inference(), excluded_hashes=set(), excluded_perceptual_hashes=set()).process(DOC)
    assert result["eligible"] == 0 and result["rejected_lineage"] == 1


def test_exact_or_perceptual_overlap_is_excluded(tmp_path):
    collector = AutomaticHoldoutCollector(tmp_path / "l.jsonl")
    exact = BackfillCoordinator(collector, Downstream(), Inference(), excluded_hashes={"sha-new"}, excluded_perceptual_hashes=set())
    assert exact.process(DOC)["status"] == "EXCLUDED_DEVELOPMENT_OVERLAP"
    near = BackfillCoordinator(collector, Downstream(), Inference(), excluded_hashes=set(), excluded_perceptual_hashes={"01234566"})
    assert near.process(DOC)["status"] == "EXCLUDED_DEVELOPMENT_OVERLAP"
