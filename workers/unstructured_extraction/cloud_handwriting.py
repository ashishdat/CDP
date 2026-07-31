"""Optional crop-only cloud handwriting boundary with a circuit breaker."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CloudHandwritingResult:
    value: str | None
    confidence: float
    provider: str
    model_version: str


class CloudHandwritingProvider(Protocol):
    def recognize_crop(
        self, crop_png: bytes, field_name: str, field_type: str
    ) -> CloudHandwritingResult: ...


class CloudProviderDisabledError(RuntimeError):
    pass


class CircuitOpenError(RuntimeError):
    pass


class CropOnlyCloudProvider:
    """Transport-neutral Azure/Google adapter; caller supplies PHI-approved transport."""

    def __init__(
        self,
        provider: str,
        endpoint: str | None,
        credential: str | None,
        transport,
        enabled: bool = False,
        timeout_seconds: float = 10,
        maximum_attempts: int = 2,
        failure_threshold: int = 3,
        reset_seconds: float = 60,
    ) -> None:
        self._provider = provider
        self._endpoint = endpoint
        self._credential = credential
        self._transport = transport
        self._enabled = enabled
        self._timeout = timeout_seconds
        self._maximum_attempts = maximum_attempts
        self._failure_threshold = failure_threshold
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None

    def recognize_crop(
        self, crop_png: bytes, field_name: str, field_type: str
    ) -> CloudHandwritingResult:
        if not self._enabled:
            raise CloudProviderDisabledError("cloud handwriting is disabled")
        if not self._endpoint or not self._credential:
            raise CloudProviderDisabledError(
                "cloud handwriting credentials/endpoint are not configured"
            )
        now = time.monotonic()
        if self._opened_at is not None and now - self._opened_at < self._reset_seconds:
            raise CircuitOpenError("cloud handwriting circuit is open")
        last_error: Exception | None = None
        for _ in range(self._maximum_attempts):
            try:
                payload = self._transport(
                    endpoint=self._endpoint,
                    credential=self._credential,
                    crop_png=crop_png,
                    field_name=field_name,
                    field_type=field_type,
                    timeout=self._timeout,
                )
                self._failures = 0
                self._opened_at = None
                return CloudHandwritingResult(
                    value=payload.get("value"),
                    confidence=float(payload.get("confidence", 0)),
                    provider=self._provider,
                    model_version=str(payload.get("model_version", "unknown")),
                )
            except Exception as exc:  # noqa: BLE001 - transport boundary must trip breaker
                last_error = exc
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._opened_at = time.monotonic()
        assert last_error is not None
        raise last_error
