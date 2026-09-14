"""Request-scoped runtime configuration, with no benchmark or truth dependency."""

from dataclasses import dataclass, field

from .models import FeatureFlags


@dataclass(frozen=True)
class PipelineContext:
    request_id: str
    flags: FeatureFlags = field(default_factory=FeatureFlags)
