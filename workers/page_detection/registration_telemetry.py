"""Execution-time registration events; no matching or failure reconstruction."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from time import perf_counter
from uuid import uuid4

LOGGER = logging.getLogger("cdp.registration.telemetry")
ACTIVE = ContextVar("registration_trace", default=None)
COLLECTION = ContextVar("registration_traces", default=None)
METADATA = ContextVar("registration_metadata", default=None)
FIELDS = ("anchor_count", "feature_count", "homography_score", "transform_residual", "confidence")
STAGES = ("Anchor Detection", "Feature Matching", "Homography", "Transform", "Acceptance")


class RegistrationTrace:
    def __init__(self, *, clock=perf_counter):
        self.clock = clock
        self.started = clock()
        self.events = []
        self.trace_id = uuid4().hex
        self.current = None
        self.stage_started = self.started
        self.values = dict.fromkeys(FIELDS)

    def emit(self, stage, status, *, reason=None, latency=0.0, **data):
        event = {"sequence": len(self.events) + 1, "trace_id": self.trace_id,
                 "timestamp": datetime.now(UTC).isoformat(), "latency": latency,
                 "latency_unit": "milliseconds", "stage": stage, "status": status,
                 **self.values, "reason": reason, "data": {**(METADATA.get() or {}), **data}}
        self.events.append(event)
        try:
            LOGGER.info("registration_event %s", json.dumps(event, allow_nan=False))
        except Exception:  # noqa: BLE001, S110 -- log sink failures cannot change registration
            pass

    def start(self, stage, **data):
        self.end("SUCCESS")
        self.current = stage
        self.stage_started = self.clock()
        self.values = dict.fromkeys(FIELDS)
        self.emit(stage, "STARTED", **data)

    def end(self, status, reason=None, **data):
        if self.current is not None:
            self.emit(self.current, status, reason=reason,
                      latency=(self.clock() - self.stage_started) * 1000, **data)
            self.current = None

    def snapshot(self):
        seen = {event["stage"] for event in self.events}
        return {"trace_id": self.trace_id, "events": list(self.events),
                "missing_events": [stage for stage in STAGES if stage not in seen]}


def stage(name, **data):
    trace = ACTIVE.get()
    if trace is not None:
        trace.start(name, **data)


def measurements(**values):
    trace = ACTIVE.get()
    if trace is not None:
        trace.values.update({key: value for key, value in values.items() if key in FIELDS})


def failed(reason, **data):
    trace = ACTIVE.get()
    if trace is not None:
        trace.end("FAILED", reason, **data)


def traced_registration(function):
    @wraps(function)
    def execute(*args, **kwargs):
        trace = RegistrationTrace()
        collection = COLLECTION.get()
        if collection is not None:
            collection.append(trace)
        token = ACTIVE.set(trace)
        trace.emit("Registration Started", "STARTED")
        trace.emit("Anchor Detection", "SKIPPED", reason="Not executed by image registration")
        try:
            result = function(*args, **kwargs)
            evidence = result.evidence.model_dump(mode="json") if result.evidence else None
            trace.end("SUCCESS" if result.accepted else "FAILED",
                      None if result.accepted else (evidence or {}).get("rejection_reason"),
                      evidence=evidence)
            trace.emit("Registration Finished", "SUCCESS" if result.accepted else "FAILED",
                       reason=None if result.accepted else (evidence or {}).get("rejection_reason"),
                       latency=(trace.clock() - trace.started) * 1000, evidence=evidence)
            return result
        except Exception as exc:
            trace.end("FAILED", type(exc).__name__)
            trace.emit("Registration Finished", "FAILED", reason=type(exc).__name__,
                       latency=(trace.clock() - trace.started) * 1000)
            raise
        finally:
            ACTIVE.reset(token)
    return execute


@contextmanager
def collect_traces():
    traces = []
    token = COLLECTION.set(traces)
    try:
        yield traces
    finally:
        COLLECTION.reset(token)


def save_traces(traces, directory):
    payload = {"type": "RegistrationTrace", "traces": [trace.snapshot() for trace in traces]}
    (Path(directory) / "registration_trace.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


@contextmanager
def registration_context(**metadata):
    token = METADATA.set(metadata)
    try:
        yield
    finally:
        METADATA.reset(token)
