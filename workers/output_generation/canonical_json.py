"""Canonical claim JSON output: a thin, versioned wrapper around the
domain `Claim` model -- this is always fully available (every field on
`Claim` is already a Pydantic model), unlike fixed-width output which
depends on how many record types are transcribed in `config/output_specs`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from packages.domain.claim import Claim

CANONICAL_JSON_SCHEMA_VERSION = "1.0"


def to_canonical_json(claim: Claim) -> dict[str, Any]:
    return {
        "schema_version": CANONICAL_JSON_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "claim": json.loads(claim.model_dump_json()),
    }


def to_canonical_json_bytes(claim: Claim) -> bytes:
    return json.dumps(to_canonical_json(claim), indent=2, sort_keys=True).encode("utf-8")
