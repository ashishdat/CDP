"""Pipeline-facing candidate ranking using the existing versioned scoring policy."""

from collections.abc import Iterable

from packages.extraction_pipeline.models import FeatureFlag
from packages.extraction_pipeline.registry import StageRegistration
from packages.extraction_recovery.contracts import CandidateObservation, CandidateRankingResult
from packages.extraction_recovery.ranking import CandidateScoringPolicy, rank_candidates


class CandidateRankingService:
    """Rank observed candidates without rewriting OCR or making acceptance decisions.

    A private policy snapshot fixes the scoring version for the service lifetime.
    Existing weights, score clipping, candidate-ID tie breaking, normalization
    fallback, and review reasons remain owned by ``rank_candidates``.
    """

    def __init__(self, policy: CandidateScoringPolicy | None = None) -> None:
        selected = policy if policy is not None else CandidateScoringPolicy.load()
        self._policy = selected.model_copy(deep=True)

    @property
    def policy_version(self) -> str:
        return self._policy.version

    def rank(self, candidates: Iterable[CandidateObservation]) -> CandidateRankingResult:
        """Return the existing result contract; preserve input objects and ordering.

        ``ranked_candidate_ids`` contains the winner first followed by losers.
        No candidate is filtered, normalized, or mutated by this service.
        """
        return rank_candidates(list(candidates), self._policy)

    def stage(self, legacy):
        """Use existing PIPELINE_V3 activation and the caller's legacy fallback."""

        def replacement(payload, context):
            return self.rank(payload)

        return StageRegistration("candidate_ranking", legacy, replacement, FeatureFlag.PIPELINE_V3)
