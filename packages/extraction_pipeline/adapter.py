"""Bridge for an existing callable; preserves argument and result identity."""

from collections.abc import Callable
from typing import Generic, TypeVar

from .context import PipelineContext
from .pipeline import ExtractionPipeline
from .registry import StageRegistration, StageRegistry

Result = TypeVar("Result")


class LegacyCallableAdapter(Generic[Result]):
    """Phase 1 bridge: V3 orchestration still executes the original callable once.

    This is opt-in wiring, not a replacement for an existing public signature.
    Worker integration must retain that signature and supply request context.
    """

    def __init__(self, legacy: Callable[..., Result]) -> None:
        self._legacy = legacy

    def invoke(self, context: PipelineContext, /, *args, **kwargs) -> Result:
        def call(_value, _context):
            return self._legacy(*args, **kwargs)

        registry = StageRegistry((StageRegistration("legacy_adapter", call, call),))
        return ExtractionPipeline(registry, call).run(None, context).value
