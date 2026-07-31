"""Prometheus metrics (exact names from the platform spec) + OpenTelemetry
tracing + PHI-redacting structured logging, shared by every app/worker."""

from packages.observability.logging import configure_logging, get_logger
from packages.observability.metrics import REGISTRY
from packages.observability.tracing import configure_tracing, get_tracer, traced_span

__all__ = [
    "REGISTRY",
    "configure_logging",
    "configure_tracing",
    "get_logger",
    "get_tracer",
    "traced_span",
]
