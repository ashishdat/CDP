"""V3 orchestration primitives. Importing this package starts no engines."""

from .context import PipelineContext
from .models import FeatureFlag, FeatureFlags
from .pipeline import ExtractionPipeline
from .registry import StageRegistry
from .results import PipelineResult

__all__ = [
    "ExtractionPipeline",
    "FeatureFlag",
    "FeatureFlags",
    "PipelineContext",
    "PipelineResult",
    "StageRegistry",
]
