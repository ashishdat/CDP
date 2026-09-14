"""Internal execution report. Public adapters return only its original value."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from .metrics import StageMetric

Payload = TypeVar("Payload")


@dataclass(frozen=True)
class PipelineResult(Generic[Payload]):
    value: Payload
    metrics: tuple[StageMetric, ...]
