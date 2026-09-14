"""Side-channel timings. Never attach telemetry to the client payload."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StageMetric:
    stage: str
    implementation: str
    elapsed_ns: int
    succeeded: bool


class NullMetricSink:
    def record(self, metric: StageMetric) -> None:
        pass
