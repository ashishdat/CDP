"""Transactional outbox pattern: DB write and event publish are decoupled.

A service writes an `OutboxRecord` in the same DB transaction as its
domain-state change. A separate `OutboxRelay` polls for unpublished
records and publishes them to the `EventBus`, marking them published only
after a successful send. This gives at-least-once delivery anchored to the
DB commit rather than to Kafka being reachable at write time.

Consumers must be idempotent (dedupe on `EventEnvelope.event_id`) since a
crash between publish and mark-published can redeliver.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)


class OutboxRecord(DomainModel):
    outbox_id: UUID = Field(default_factory=new_id)
    topic: str
    envelope: EventEnvelope
    partition_key: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = None
    publish_attempts: int = 0
    last_error: str | None = None


class OutboxRepository(Protocol):
    """Implemented against the real DB (SQLAlchemy) by each service."""

    async def add(self, record: OutboxRecord) -> None: ...

    async def get_unpublished(self, limit: int = 100) -> list[OutboxRecord]: ...

    async def mark_published(self, outbox_id: UUID) -> None: ...

    async def mark_failed(self, outbox_id: UUID, error: str) -> None: ...


class OutboxRelay:
    """Polling relay. Run as a background task in each service that writes
    to the outbox."""

    def __init__(
        self,
        repository: OutboxRepository,
        event_bus: EventBus,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 100,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._stop_event = asyncio.Event()

    async def run_once(self) -> int:
        records = await self._repository.get_unpublished(limit=self._batch_size)
        published = 0
        for record in records:
            try:
                await self._event_bus.publish(
                    record.topic, record.envelope, key=record.partition_key
                )
                await self._repository.mark_published(record.outbox_id)
                published += 1
            except Exception as exc:  # noqa: BLE001 - relay must keep going
                logger.warning("outbox publish failed outbox_id=%s: %s", record.outbox_id, exc)
                await self._repository.mark_failed(record.outbox_id, str(exc))
        return published

    async def run_forever(self) -> None:
        while not self._stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval_seconds
                )
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop_event.set()
