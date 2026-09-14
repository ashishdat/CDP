"""Ports accept existing payloads without normalizing or serializing them."""

from typing import Protocol, TypeVar

from .context import PipelineContext
from .metrics import StageMetric

Payload = TypeVar("Payload")


class Stage(Protocol[Payload]):
    def __call__(self, payload: Payload, context: PipelineContext) -> Payload: ...


class MetricSink(Protocol):
    def record(self, metric: StageMetric) -> None: ...
