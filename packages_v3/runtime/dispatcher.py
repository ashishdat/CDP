"""Request-local feature dispatch with fail-isolated shadow diagnostics."""

from copy import deepcopy
from time import perf_counter_ns

from .integration import RuntimeIntegration
from .metrics import comparison, emit, log_report
from .models import (
    STAGES,
    CoverageReport,
    ExecutionState,
    PipelineMetrics,
    RuntimeReport,
    StageCoverage,
)


class RuntimeDispatcher:
    def __init__(self, adapter, *, sink=log_report, clock=perf_counter_ns):
        self.adapter = adapter
        self.sink = sink
        self.clock = clock

    def execute(self, request, flags, *, request_id=""):
        started = self.clock()
        legacy_ns = v3_ns = 0
        legacy_value = v3_value = None
        legacy_snapshots = {}
        state = ExecutionState(None)
        comparable = False
        error_type = None
        try:
            if flags.mode == "v3":
                begin = self.clock()
                try:
                    return RuntimeIntegration(self.adapter, clock=self.clock).run(
                        request, flags, request_id, state
                    )
                finally:
                    v3_ns = self.clock() - begin
            shadow_request = None
            shadow_ready = False
            if flags.mode == "shadow":
                try:
                    if not self.adapter.shadow_safe:
                        raise ValueError("Shadow-safe callbacks are required")
                    shadow_request = self.adapter.clone_request(request)
                    shadow_ready = True
                except Exception as exc:  # noqa: BLE001 -- preserve the legacy request
                    error_type = type(exc).__name__
            begin = self.clock()
            try:
                legacy_value = self.adapter.legacy(request)
            finally:
                legacy_ns = self.clock() - begin
            if shadow_ready:
                begin = self.clock()
                try:
                    v3_value = RuntimeIntegration(self.adapter, clock=self.clock).run(
                        shadow_request, flags, request_id, state
                    )
                    comparable = True
                    legacy_snapshots = deepcopy(self.adapter.legacy_snapshots(legacy_value))
                except Exception as exc:  # noqa: BLE001 -- shadow never changes legacy success
                    error_type = type(exc).__name__
                finally:
                    v3_ns = self.clock() - begin
            return legacy_value
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            try:
                report = RuntimeReport(
                    request_id,
                    flags.mode,
                    comparison(
                        legacy_snapshots,
                        state.snapshots,
                        legacy_value,
                        v3_value,
                        comparable=comparable,
                    ),
                    CoverageReport(
                        tuple(
                            state.coverage.get(
                                name, StageCoverage(name, "skipped", "unknown", "NOT_OBSERVED")
                            )
                            for name in STAGES
                        )
                    ),
                    PipelineMetrics(
                        tuple((name, state.latency_ns.get(name, 0)) for name in STAGES),
                        legacy_ns,
                        v3_ns,
                        self.clock() - started,
                    ),
                    error_type,
                )
                emit(self.sink, report)
            except Exception:  # noqa: BLE001, S110 -- diagnostics cannot mask runtime outcomes
                pass
