"""Canonical event envelope, topic registry, and Kafka-compatible bus abstraction."""

from packages.events.bus import AIOKafkaEventBus, EventBus, InMemoryEventBus
from packages.events.envelope import EventEnvelope, TraceContext
from packages.events.outbox import OutboxRecord, OutboxRelay, OutboxRepository
from packages.events.topics import Topic

__all__ = [
    "AIOKafkaEventBus",
    "EventBus",
    "EventEnvelope",
    "InMemoryEventBus",
    "OutboxRecord",
    "OutboxRelay",
    "OutboxRepository",
    "Topic",
    "TraceContext",
]
