"""Canonical Kafka event envelope.

Every event on every topic is one of these. `payload` is a nested,
topic-specific Pydantic model — but it must never carry raw document/image
bytes, only object-storage URIs (enforced by `assert_no_bytes_payload`
below, invoked by the EventBus before publish).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow


class TraceContext(DomainModel):
    """W3C traceparent-shaped context for OpenTelemetry propagation."""

    trace_id: str
    span_id: str
    trace_flags: str = "01"


class EventEnvelope(DomainModel):
    event_id: UUID = Field(default_factory=new_id)
    event_type: str
    event_version: str = "1.0"
    occurred_at: datetime = Field(default_factory=utcnow)
    correlation_id: UUID
    document_id: UUID | None = None
    claim_id: UUID | None = None
    attempt: int = Field(ge=1, default=1)
    pipeline_version: str
    payload: dict[str, Any]
    trace_context: TraceContext | None = None

    def assert_no_bytes_payload(self) -> None:
        _reject_bytes(self.payload, path="payload")


def _reject_bytes(value: Any, path: str) -> None:
    if isinstance(value, (bytes, bytearray)):
        raise ValueError(
            f"Event payload at '{path}' contains raw bytes; Kafka events must "
            "carry object-storage URIs, never document/image bytes."
        )
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_bytes(v, path=f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _reject_bytes(v, path=f"{path}[{i}]")
