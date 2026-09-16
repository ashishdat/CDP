"""Azure Document Intelligence prebuilt-read REST backend (crop-only).

Uses the Document Intelligence analyze API with polling. Credentials stay in
Settings / env — never logged or persisted on candidates.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from workers.cascade.azure_read_adapter import AzureReadEvidence


class AzureDocumentIntelligenceReadBackend:
    """Synchronous prebuilt-read client for regional field crops."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        api_version: str = "2024-11-30",
        model_id: str = "prebuilt-read",
        timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.2,
    max_polls: int = 30,
        opener=None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._api_version = api_version
        self._model_id = model_id
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._max_polls = max_polls
        self._opener = opener or urlopen

    def analyze(self, image_bytes: bytes) -> AzureReadEvidence:
        if not image_bytes:
            return AzureReadEvidence("", 0.0, False)
        operation = self._start_analyze(image_bytes)
        payload = self._poll_result(operation)
        return self._to_evidence(payload)

    def _start_analyze(self, image_bytes: bytes) -> str:
        url = (
            f"{self._endpoint}/documentintelligence/documentModels/"
            f"{self._model_id}:analyze?api-version={self._api_version}"
        )
        request = Request(
            url,
            data=image_bytes,
            method="POST",
            headers={
                "Ocp-Apim-Subscription-Key": self._api_key,
                "Content-Type": "application/octet-stream",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                location = response.headers.get("operation-location") or response.headers.get(
                    "Operation-Location"
                )
                if not location:
                    raise RuntimeError("Azure DI analyze missing operation-location")
                return location
        except HTTPError as exc:
            body = exc.read()[:300].decode("utf-8", "replace")
            raise RuntimeError(f"Azure DI analyze HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Azure DI analyze transport error: {exc}") from exc

    def _poll_result(self, operation_url: str) -> dict[str, Any]:
        for _ in range(self._max_polls):
            request = Request(
                operation_url,
                method="GET",
                headers={"Ocp-Apim-Subscription-Key": self._api_key},
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    import json

                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read()[:300].decode("utf-8", "replace")
                raise RuntimeError(f"Azure DI poll HTTP {exc.code}: {body}") from exc
            status = str(payload.get("status") or "").lower()
            if status in {"succeeded", "failed", "canceled", "cancelled"}:
                if status != "succeeded":
                    raise RuntimeError(f"Azure DI analyze ended with status={status}")
                return payload
            time.sleep(self._poll_interval)
        raise RuntimeError("Azure DI analyze timed out waiting for result")

    def _to_evidence(self, payload: dict[str, Any]) -> AzureReadEvidence:
        result = payload.get("analyzeResult") or payload.get("analyze_result") or {}
        content = str(result.get("content") or "").strip()
        styles = result.get("styles") or []
        handwritten = any(bool(style.get("isHandwritten")) for style in styles)
        confidences: list[float] = []
        for page in result.get("pages") or []:
            for word in page.get("words") or []:
                if "confidence" in word:
                    confidences.append(float(word["confidence"]))
            for line in page.get("lines") or []:
                if "confidence" in line:
                    confidences.append(float(line["confidence"]))
        confidence = sum(confidences) / len(confidences) if confidences else (0.7 if content else 0.0)
        return AzureReadEvidence(content, confidence, handwritten)


def azure_di_handwriting_transport(
    *,
    endpoint: str,
    credential: str,
    crop_png: bytes,
    field_name: str,
    field_type: str,
    timeout: float = 30.0,
    api_version: str = "2024-11-30",
) -> dict[str, Any]:
    """Transport adapter for CropOnlyCloudProvider → Azure DI Read."""
    del field_name, field_type  # crop-only; field metadata is not sent to Azure
    backend = AzureDocumentIntelligenceReadBackend(
        endpoint,
        credential,
        api_version=api_version,
        timeout_seconds=timeout,
    )
    evidence = backend.analyze(crop_png)
    return {
        "value": evidence.text.strip() or None,
        "confidence": evidence.confidence,
        "model_version": f"prebuilt-read@{api_version}",
        "handwritten": evidence.handwritten,
    }
