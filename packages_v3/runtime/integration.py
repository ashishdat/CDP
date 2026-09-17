"""Compose supplied runtime operations through the existing Phase 1 pipeline."""

from copy import deepcopy
from time import perf_counter_ns

from packages.extraction_pipeline import (
    ExtractionPipeline,
    FeatureFlag,
    FeatureFlags,
    PipelineContext,
    StageRegistry,
)
from packages.extraction_pipeline.registry import StageRegistration

from .models import STAGES, StageCoverage


class RuntimeIntegration:
    def __init__(self, adapter, *, clock=perf_counter_ns):
        self.adapter = adapter
        self.clock = clock

    def run(self, request, flags, request_id, state):
        state.value = self.adapter.to_pipeline(request)
        registrations = []
        for name in STAGES:

            def execute(current, context, stage=name):
                try:
                    operation, implementation, reason = self.adapter.operation(stage, flags)
                except Exception:
                    current.coverage[stage] = StageCoverage(
                        stage, "failed", "unknown", "BINDING_FAILED"
                    )
                    raise
                if operation is None:
                    current.coverage[stage] = StageCoverage(
                        stage, "skipped", implementation, reason
                    )
                    return current
                started = self.clock()
                try:
                    current.value = operation(current.value)
                except Exception:
                    current.coverage[stage] = StageCoverage(
                        stage, "failed", implementation, "STAGE_FAILED"
                    )
                    raise
                else:
                    current.coverage[stage] = StageCoverage(
                        stage, "executed", implementation, reason
                    )
                    try:
                        current.snapshots[stage] = deepcopy(
                            self.adapter.project(stage, current.value)
                        )
                    except Exception:  # noqa: BLE001, S110 -- snapshot failures are diagnostic only
                        pass
                finally:
                    current.latency_ns[stage] = self.clock() - started
                return current

            registrations.append(StageRegistration(name, execute, execute))
        context = PipelineContext(request_id, FeatureFlags({FeatureFlag.PIPELINE_V3}))
        pipeline = ExtractionPipeline(
            StageRegistry(tuple(registrations)), lambda value, ctx: value, clock=self.clock
        )
        result = pipeline.run(state, context)
        return self.adapter.from_pipeline(result.value.value)
