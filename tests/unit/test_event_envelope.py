"""Canonical event envelope: required fields, and the "no bytes in Kafka
payloads" invariant."""

from uuid import uuid4

import pytest

from packages.events.envelope import EventEnvelope


def _make_envelope(**overrides) -> EventEnvelope:
    defaults = {
        "event_type": "document.received",
        "correlation_id": uuid4(),
        "pipeline_version": "0.1.0",
        "payload": {"document_id": str(uuid4()), "source_object": {"bucket": "b", "key": "k"}},
    }
    defaults.update(overrides)
    return EventEnvelope(**defaults)


def test_envelope_has_all_canonical_fields():
    envelope = _make_envelope()
    for field in (
        "event_id",
        "event_type",
        "event_version",
        "occurred_at",
        "correlation_id",
        "document_id",
        "claim_id",
        "attempt",
        "pipeline_version",
        "payload",
        "trace_context",
    ):
        assert hasattr(envelope, field)


def test_envelope_rejects_raw_bytes_in_payload():
    envelope = _make_envelope(payload={"blob": b"not allowed"})
    with pytest.raises(ValueError, match="raw bytes"):
        envelope.assert_no_bytes_payload()


def test_envelope_rejects_raw_bytes_nested_in_payload():
    envelope = _make_envelope(payload={"nested": {"deep": [1, 2, b"still not allowed"]}})
    with pytest.raises(ValueError, match="raw bytes"):
        envelope.assert_no_bytes_payload()


def test_envelope_accepts_object_uri_payload():
    envelope = _make_envelope(
        payload={"source_object": {"bucket": "b", "key": "documents/ab/cd/hash_file.tiff"}}
    )
    envelope.assert_no_bytes_payload()  # must not raise


def test_envelope_round_trips_through_json():
    envelope = _make_envelope()
    restored = EventEnvelope.model_validate_json(envelope.model_dump_json())
    assert restored.event_id == envelope.event_id
    assert restored.correlation_id == envelope.correlation_id
    assert restored.payload == envelope.payload
