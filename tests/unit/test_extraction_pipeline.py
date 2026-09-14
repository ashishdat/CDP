from concurrent.futures import ThreadPoolExecutor

import pytest

from packages.extraction_pipeline import (
    ExtractionPipeline,
    FeatureFlag,
    FeatureFlags,
    PipelineContext,
    StageRegistry,
)
from packages.extraction_pipeline.adapter import LegacyCallableAdapter
from packages.extraction_pipeline.exceptions import PipelineConfigurationError
from packages.extraction_pipeline.registry import StageRegistration


def context(*flags):
    return PipelineContext("synthetic-request", FeatureFlags(frozenset(flags)))


def test_default_flags_invoke_whole_legacy_once_and_preserve_identity():
    calls = []
    original = {"raw_value": "  original OCR  ", "candidates": []}

    def legacy(value, ctx):
        calls.append(value)
        return original

    def forbidden(*args):
        pytest.fail("disabled V3 must not run any registered stages")

    registry = StageRegistry((StageRegistration("extract", forbidden, forbidden),))
    result = ExtractionPipeline(registry, legacy).run(original, context())
    assert result.value is original
    assert calls == [original]
    assert result.metrics[0].implementation == "legacy"


def test_explicit_order_and_independent_module_rollback():
    calls = []

    def step(name):
        def execute(value, ctx):
            calls.append(name)
            return value + [name]

        return execute

    registry = StageRegistry(
        (
            StageRegistration("geometry", step("g2"), step("g3"), FeatureFlag.GEOMETRY_V3),
            StageRegistration("ocr", step("o2"), step("o3"), FeatureFlag.OCR_ROUTER_V3),
        )
    )
    pipeline = ExtractionPipeline(registry, step("whole-legacy"))
    result = pipeline.run([], context(FeatureFlag.PIPELINE_V3, FeatureFlag.OCR_ROUTER_V3))
    assert result.value == calls == ["g2", "o3"]
    assert [metric.stage for metric in result.metrics] == ["geometry", "ocr"]


def test_failure_preserves_original_exception_stops_pipeline_and_does_not_retry():
    error = RuntimeError("engine failure")
    calls = []
    recorded = []

    def fail(value, ctx):
        calls.append("failure")
        raise error

    def forbidden(value, ctx):
        pytest.fail("cannot proceed after a failed stage")

    class Sink:
        def record(self, metric):
            recorded.append(metric)
            raise OSError("telemetry unavailable")

    registry = StageRegistry(
        (
            StageRegistration("fail", fail, fail),
            StageRegistration("later", forbidden, forbidden),
        )
    )
    ticks = iter([10, 30])
    pipeline = ExtractionPipeline(
        registry, forbidden, metric_sink=Sink(), clock=lambda: next(ticks)
    )
    with pytest.raises(RuntimeError) as caught:
        pipeline.run(None, context(FeatureFlag.PIPELINE_V3))
    assert caught.value is error
    assert calls == ["failure"]
    assert recorded[0].elapsed_ns == 20
    assert recorded[0].succeeded is False


def test_sink_failure_cannot_change_successful_result():
    class Sink:
        def record(self, metric):
            raise RuntimeError("sink failure")

    identity = lambda value, ctx: value
    pipeline = ExtractionPipeline(
        StageRegistry((StageRegistration("identity", identity, identity),)),
        identity,
        metric_sink=Sink(),
    )
    original = object()
    assert pipeline.run(original, context(FeatureFlag.PIPELINE_V3)).value is original


@pytest.mark.parametrize("enabled", [False, True])
def test_adapter_preserves_positional_keyword_and_result_identity(enabled):
    payload = object()
    option = object()
    output = object()
    calls = []

    def original(value, *, selection):
        assert value is payload
        assert selection is option
        calls.append(1)
        return output

    flags = (FeatureFlag.PIPELINE_V3,) if enabled else ()
    assert (
        LegacyCallableAdapter(original).invoke(context(*flags), payload, selection=option) is output
    )
    assert calls == [1]


def test_registry_snapshots_input_and_rejects_ambiguous_order():
    identity = lambda value, ctx: value
    stage = StageRegistration("one", identity, identity)
    supplied = [stage]
    registry = StageRegistry(supplied)
    supplied.clear()
    assert registry.stages == (stage,)
    with pytest.raises(PipelineConfigurationError):
        StageRegistry((stage, stage))
    with pytest.raises(PipelineConfigurationError):
        StageRegistry(())


@pytest.mark.parametrize("value", ["true", "1", "YES", " on "])
def test_flags_require_explicit_activation(value):
    flags = FeatureFlags.from_mapping({"OCR_ROUTER_V3": value})
    assert flags.allows(FeatureFlag.OCR_ROUTER_V3)
    assert not flags.allows(FeatureFlag.PIPELINE_V3)


def test_invalid_flag_configuration_fails_before_execution():
    with pytest.raises(ValueError, match="PIPELINE_V3"):
        FeatureFlags.from_mapping({"PIPELINE_V3": "tru"})
    supplied = {FeatureFlag.PIPELINE_V3}
    flags = FeatureFlags(supplied)
    supplied.clear()
    assert flags.allows(FeatureFlag.PIPELINE_V3)


def test_concurrent_synthetic_requests_do_not_share_reports_or_payloads():
    identity = lambda value, ctx: value
    pipeline = ExtractionPipeline(
        StageRegistry((StageRegistration("identity", identity, identity),)),
        identity,
    )
    inputs = [{"request": i} for i in range(100)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda value: pipeline.run(value, context(FeatureFlag.PIPELINE_V3)),
                inputs,
            )
        )
    assert all(result.value is value for result, value in zip(results, inputs))
    assert len({id(result.metrics) for result in results}) == len(inputs)
