"""Outbox pattern: relay publishes unpublished records and marks them
published; a failing publish is recorded, not silently dropped."""

from uuid import UUID, uuid4

import pytest

from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord, OutboxRelay
from packages.events.topics import Topic


class InMemoryOutboxRepository:
    """Implements `packages.events.outbox.OutboxRepository` for tests."""

    def __init__(self) -> None:
        self._records: dict[UUID, OutboxRecord] = {}

    async def add(self, record: OutboxRecord) -> None:
        self._records[record.outbox_id] = record

    async def get_unpublished(self, limit: int = 100) -> list[OutboxRecord]:
        return [r for r in self._records.values() if r.published_at is None][:limit]

    async def mark_published(self, outbox_id: UUID) -> None:
        from packages.domain.common import utcnow

        self._records[outbox_id].published_at = utcnow()

    async def mark_failed(self, outbox_id: UUID, error: str) -> None:
        record = self._records[outbox_id]
        record.publish_attempts += 1
        record.last_error = error


def _make_record(topic: str = Topic.DOCUMENT_RECEIVED.value) -> OutboxRecord:
    envelope = EventEnvelope(
        event_type=topic,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={"document_id": str(uuid4())},
    )
    return OutboxRecord(topic=topic, envelope=envelope)


@pytest.mark.asyncio
async def test_relay_publishes_unpublished_records_and_marks_them_published():
    repo = InMemoryOutboxRepository()
    bus = InMemoryEventBus()
    record = _make_record()
    await repo.add(record)

    relay = OutboxRelay(repository=repo, event_bus=bus)
    published_count = await relay.run_once()

    assert published_count == 1
    assert record.outbox_id not in [
        r.outbox_id for r in await repo.get_unpublished()
    ]
    assert len(bus.published) == 1
    assert bus.published[0][0] == Topic.DOCUMENT_RECEIVED.value


@pytest.mark.asyncio
async def test_relay_does_not_republish_already_published_records():
    repo = InMemoryOutboxRepository()
    bus = InMemoryEventBus()
    await repo.add(_make_record())

    relay = OutboxRelay(repository=repo, event_bus=bus)
    await relay.run_once()
    second_pass_count = await relay.run_once()

    assert second_pass_count == 0
    assert len(bus.published) == 1


@pytest.mark.asyncio
async def test_relay_records_failure_without_crashing():
    class FailingBus(InMemoryEventBus):
        async def publish(self, topic, envelope, key=None):
            raise ConnectionError("broker unreachable")

    repo = InMemoryOutboxRepository()
    record = _make_record()
    await repo.add(record)

    relay = OutboxRelay(repository=repo, event_bus=FailingBus())
    published_count = await relay.run_once()

    assert published_count == 0
    assert record.publish_attempts == 1
    assert "broker unreachable" in record.last_error
    # still unpublished, eligible for retry on the next poll
    assert len(await repo.get_unpublished()) == 1


@pytest.mark.asyncio
async def test_in_memory_bus_fanout_to_multiple_consumer_groups():
    bus = InMemoryEventBus()
    envelope = EventEnvelope(
        event_type=Topic.DOCUMENT_RECEIVED.value,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={},
    )

    # register both groups before publishing (matches Kafka: a consumer
    # group only sees messages published after it starts consuming)
    bus._register_group(Topic.DOCUMENT_RECEIVED.value, "group-a")
    bus._register_group(Topic.DOCUMENT_RECEIVED.value, "group-b")

    await bus.publish(Topic.DOCUMENT_RECEIVED.value, envelope)

    queue_a = bus._queues[(Topic.DOCUMENT_RECEIVED.value, "group-a")]
    queue_b = bus._queues[(Topic.DOCUMENT_RECEIVED.value, "group-b")]
    assert queue_a.qsize() == 1
    assert queue_b.qsize() == 1
