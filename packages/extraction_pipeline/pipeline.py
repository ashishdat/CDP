"""Sequential orchestration with exact legacy fallback and no retries."""

from collections.abc import Callable
from time import perf_counter_ns
from typing import Generic, TypeVar

from .context import PipelineContext
from .interfaces import MetricSink, Stage
from .metrics import NullMetricSink, StageMetric
from .models import FeatureFlag
from .registry import StageRegistry
from .results import PipelineResult

Payload = TypeVar("Payload")


class ExtractionPipeline(Generic[Payload]):
    def __init__(
        self,
        registry: StageRegistry[Payload],
        legacy: Stage[Payload],
        *,
        metric_sink: MetricSink | None = None,
        clock: Callable[[], int] = perf_counter_ns,
    ) -> None:
        self._registry = registry
        self._legacy = legacy
        self._sink = metric_sink if metric_sink is not None else NullMetricSink()
        self._clock = clock

    def run(self, payload: Payload, context: PipelineContext) -> PipelineResult[Payload]:
        metrics: list[StageMetric] = []

        def invoke(name: str, implementation: str, stage: Stage[Payload], value: Payload):
            started = self._clock()
            succeeded = False
            try:
                result = stage(value, context)
                succeeded = True
                return result
            finally:
                metric = StageMetric(name, implementation, self._clock() - started, succeeded)
                metrics.append(metric)
                try:
                    self._sink.record(metric)
                except Exception:  # noqa: BLE001, S110 -- preserve engine errors on sink failure
                    # Observability outages cannot change production decisions or errors.
                    pass

        if not context.flags.allows(FeatureFlag.PIPELINE_V3):
            value = invoke("legacy_pipeline", "legacy", self._legacy, payload)
        else:
            value = payload
            for registration in self._registry.stages:
                enabled = context.flags.allows(registration.flag)
                stage = registration.replacement if enabled else registration.legacy
                value = invoke(registration.name, "v3" if enabled else "legacy", stage, value)
        return PipelineResult(value, tuple(metrics))
