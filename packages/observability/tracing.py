"""OpenTelemetry tracer setup, shared by every app/worker so spans from
different services correlate under one trace (propagated via
`packages.events.envelope.TraceContext`, carried on every Kafka event)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span, Status, StatusCode

_configured = False


def configure_tracing(service_name: str) -> TracerProvider:
    """Idempotent: safe to call more than once (e.g. in tests) without
    stacking duplicate providers."""
    global _configured
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    if not _configured:
        trace.set_tracer_provider(provider)
        _configured = True
    return provider


def get_tracer(name: str):
    return trace.get_tracer(name)


@contextmanager
def traced_span(tracer, name: str, **attributes: str) -> Iterator[Span]:
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
