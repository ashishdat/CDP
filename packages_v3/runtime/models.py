"""Internal diagnostics only: never added to legacy API responses."""

from dataclasses import dataclass, field
from typing import Any

STAGES = ("geometry", "ocr", "ranking", "validators", "decision", "evidence")


@dataclass(frozen=True)
class StageCoverage:
    stage: str
    status: str
    implementation: str
    reason: str


@dataclass(frozen=True)
class CoverageReport:
    stages: tuple[StageCoverage, ...]

    @property
    def coverage_percent(self) -> float:
        return 100 * sum(stage.status == "executed" for stage in self.stages) / len(STAGES)


@dataclass(frozen=True)
class PipelineComparison:
    stages: tuple[tuple[str, str], ...]
    response: str


@dataclass(frozen=True)
class PipelineMetrics:
    stage_latency_ns: tuple[tuple[str, int], ...]
    legacy_latency_ns: int
    v3_latency_ns: int
    total_latency_ns: int


@dataclass(frozen=True)
class RuntimeReport:
    request_id: str
    mode: str
    comparison: PipelineComparison
    coverage: CoverageReport
    metrics: PipelineMetrics
    error_type: str | None = None


@dataclass
class ExecutionState:
    value: Any
    snapshots: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, StageCoverage] = field(default_factory=dict)
    latency_ns: dict[str, int] = field(default_factory=dict)
