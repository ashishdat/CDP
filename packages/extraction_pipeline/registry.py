"""Explicit immutable stage ordering; no import discovery or global registry."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from .exceptions import PipelineConfigurationError
from .interfaces import Stage
from .models import FeatureFlag

Payload = TypeVar("Payload")


@dataclass(frozen=True)
class StageRegistration(Generic[Payload]):
    name: str
    legacy: Stage[Payload]
    replacement: Stage[Payload]
    flag: FeatureFlag = FeatureFlag.PIPELINE_V3

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise PipelineConfigurationError("Stage name must be nonempty")
        if not callable(self.legacy) or not callable(self.replacement):
            raise PipelineConfigurationError("Both stage implementations must be callable")
        object.__setattr__(self, "flag", FeatureFlag(self.flag))


@dataclass(frozen=True)
class StageRegistry(Generic[Payload]):
    stages: tuple[StageRegistration[Payload], ...]

    def __post_init__(self) -> None:
        stages = tuple(self.stages)
        if not stages:
            raise PipelineConfigurationError("At least one stage is required")
        names = [stage.name for stage in stages]
        if len(names) != len(set(names)):
            raise PipelineConfigurationError("Stage names must be unique")
        object.__setattr__(self, "stages", stages)
