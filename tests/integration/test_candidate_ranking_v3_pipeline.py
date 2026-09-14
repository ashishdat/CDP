import pytest

from packages.candidate_ranking import CandidateRankingService
from packages.extraction_pipeline import (
    ExtractionPipeline,
    FeatureFlag,
    FeatureFlags,
    PipelineContext,
    StageRegistry,
)
from packages.extraction_recovery.ranking import CandidateScoringPolicy, rank_candidates


@pytest.mark.parametrize("enabled", [False, True])
def test_pipeline_ranking_and_legacy_rollback(enabled):
    calls = []
    sentinel = object()
    inputs = []

    def legacy(payload, context):
        assert payload is inputs
        calls.append(1)
        return sentinel

    service = CandidateRankingService()
    pipeline = ExtractionPipeline(StageRegistry((service.stage(legacy),)), legacy)
    flags = FeatureFlags({FeatureFlag.PIPELINE_V3} if enabled else set())
    result = pipeline.run(inputs, PipelineContext("ranking-test", flags))
    if enabled:
        assert result.value == rank_candidates(inputs, CandidateScoringPolicy.load())
        assert result.metrics[0].stage == "candidate_ranking"
        assert not calls
    else:
        assert result.value is sentinel
        assert calls == [1]


def test_disabled_pipeline_preserves_legacy_exception_identity():
    error = RuntimeError("legacy failure")

    def legacy(payload, context):
        raise error

    service = CandidateRankingService()
    pipeline = ExtractionPipeline(StageRegistry((service.stage(legacy),)), legacy)
    with pytest.raises(RuntimeError) as caught:
        pipeline.run([], PipelineContext("ranking-test"))
    assert caught.value is error
