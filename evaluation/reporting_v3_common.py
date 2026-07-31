"""Pure helpers shared by the versioned production reporting commands."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

IDENTITY_KEYS = (
    "document_id", "page_number", "document_family", "form_version",
    "form_locator", "service_line_number", "semantic_field",
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def identity_key(identity: dict) -> tuple:
    return tuple(identity.get(key) for key in IDENTITY_KEYS)


def normalize(value: object, data_type: str) -> str:
    raw = str(value or "").strip().upper()
    if data_type in {"currency", "amount"}:
        cleaned = re.sub(r"[^0-9.\-]", "", raw)
        if cleaned and "." not in cleaned and len(cleaned) > 2:
            cleaned = f"{cleaned[:-2]}.{cleaned[-2:]}"
        return cleaned
    if data_type in {"date", "numeric", "number", "integer", "zip", "npi"}:
        return re.sub(r"\D", "", raw)
    return re.sub(r"[^A-Z0-9]", "", raw)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def assert_unique(fields: list[dict]) -> None:
    keys = [identity_key(row["field_identity"]) for row in fields]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate semantic field identity in evaluation contract")


def contract_checksum(contract: dict) -> str:
    payload = {key: value for key, value in contract.items() if key != "contract_sha256"}
    return sha256_bytes(canonical_json(payload))
