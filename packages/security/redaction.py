"""Structured PHI redaction: a `structlog` processor that masks known
PHI-risk keys wherever they appear in a log event, recursively through
nested dicts/lists -- "structured" because it acts on field *names*, not
by scanning free text for patterns (which is unreliable and out of scope
here). Field *names* (e.g. `"field_name": "patient_name"`) are safe to
log; field *values* are not.
"""

from __future__ import annotations

from typing import Any

REDACTED = "[REDACTED]"

# Key names (case-insensitive, matched as substrings) whose *values* may
# carry PHI and must never reach logs/traces/metrics. Deliberately broad --
# false positives (over-redacting) are a much smaller problem than PHI in
# a log aggregator.
PHI_KEY_MARKERS = (
    "raw_value",
    "normalized_value",
    "patient_name",
    "insured_name",
    "provider_name",
    "patient_address",
    "insured_address",
    "provider_address",
    "address",
    "dob",
    "date_of_birth",
    "birth_date",
    "ssn",
    "phone",
    "telephone",
    "email",
    "tax_id",
    "npi",
    "policy_number",
    "member_id",
    "subscriber_id",
    "patient_control_number",
    "diagnosis",
    "raw_text",
)


def _is_phi_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in PHI_KEY_MARKERS)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if _is_phi_key(k) else redact_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_phi_processor(logger: Any, method_name: str, event_dict: dict) -> dict:
    """A structlog processor -- add via `structlog.configure(processors=[...
    redact_phi_processor, ...])`."""
    del logger, method_name
    return {k: (REDACTED if _is_phi_key(k) else redact_value(v)) for k, v in event_dict.items()}
