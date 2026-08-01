"""Fail-closed routing for expensive crop-level fallback inference.

Reference decisions are evaluated before local evidence and cloud inference.  Cloud
results may be reused only when the crop and every policy/model input are identical.
The cache is an inference cache, not an authority source: a cached REVIEW_ONLY
candidate remains REVIEW_ONLY.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class FallbackAction(StrEnum):
    REFERENCE_VERIFIED = "REFERENCE_VERIFIED"
    LOCAL_ACCEPTED = "LOCAL_ACCEPTED"
    CACHED_CLOUD_EVIDENCE = "CACHED_CLOUD_EVIDENCE"
    CALL_CLOUD = "CALL_CLOUD"


@dataclass(frozen=True)
class FallbackRequest:
    identity_key: str
    crop_sha256: str
    prompt_version: str
    model_version: str
    normalization_version: str
    validation_policy_version: str

    @property
    def cache_key(self) -> str:
        payload = (
            f"{self.identity_key}|{self.crop_sha256}|{self.prompt_version}|"
            f"{self.model_version}|{self.normalization_version}|"
            f"{self.validation_policy_version}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FallbackDecision:
    action: FallbackAction
    evidence: Mapping[str, Any] | None = None
    automatically_acceptable: bool = False


class GovernedInferenceCache:
    """Content-addressed cache with atomic replacement and no authority elevation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._rows: dict[str, dict[str, Any]] = {}
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._rows = {str(row["cache_key"]): row for row in raw}

    def get(self, request: FallbackRequest) -> Mapping[str, Any] | None:
        row = self._rows.get(request.cache_key)
        return row.get("evidence") if row else None

    def put(self, request: FallbackRequest, evidence: Mapping[str, Any]) -> None:
        # Cache reuse must never convert review evidence into accepted evidence.
        stored = dict(evidence)
        stored["automatically_acceptable"] = bool(
            evidence.get("automatically_acceptable", False)
        )
        self._rows[request.cache_key] = {
            "cache_key": request.cache_key,
            "identity_key": request.identity_key,
            "crop_sha256": request.crop_sha256,
            "prompt_version": request.prompt_version,
            "model_version": request.model_version,
            "normalization_version": request.normalization_version,
            "validation_policy_version": request.validation_policy_version,
            "evidence": stored,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(list(self._rows.values()), indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)


def verified_reference_keys(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        str(row["identity_key"])
        for row in rows
        if row.get("decision") == "REFERENCE_VERIFIED"
    }


def route_fallback(
    request: FallbackRequest,
    *,
    reference_keys: set[str],
    local_evidence: Mapping[str, Any] | None,
    cache: GovernedInferenceCache,
) -> FallbackDecision:
    """Choose the cheapest safe evidence source in deterministic priority order."""
    if request.identity_key in reference_keys:
        return FallbackDecision(FallbackAction.REFERENCE_VERIFIED, automatically_acceptable=True)
    if local_evidence and local_evidence.get("route_promoted") is True:
        return FallbackDecision(
            FallbackAction.LOCAL_ACCEPTED,
            evidence=local_evidence,
            automatically_acceptable=True,
        )
    cached = cache.get(request)
    if cached is not None:
        return FallbackDecision(
            FallbackAction.CACHED_CLOUD_EVIDENCE,
            evidence=cached,
            automatically_acceptable=bool(cached.get("automatically_acceptable", False)),
        )
    return FallbackDecision(FallbackAction.CALL_CLOUD)
