"""PHI-gated Azure Document Intelligence Read shadow adapter."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Protocol

from packages.ocr.contracts import OCRCandidate, OCRRequest


@dataclass(frozen=True)
class AzureReadEvidence:
    text: str
    confidence: float
    handwritten: bool


class AzureReadBackend(Protocol):
    def analyze(self, image_bytes: bytes) -> AzureReadEvidence: ...


class AzureReadShadowEngine:
    def __init__(
        self,
        backend: AzureReadBackend | None = None,
        *,
        authorized: bool = False,
        region_approved: bool = False,
        phi_contract_approved: bool = False,
        provider_version: str = "2024-11-30",
    ) -> None:
        self._backend = backend
        self._authorized = authorized
        self._region_approved = region_approved
        self._phi_contract_approved = phi_contract_approved
        self._provider_version = provider_version

    @property
    def engine_name(self) -> str:
        return "azure_document_intelligence_read"

    @property
    def model_name(self) -> str:
        return "prebuilt-read"

    @property
    def model_version(self) -> str:
        return self._provider_version

    def recognize(self, request: OCRRequest) -> list[OCRCandidate]:
        if not all((
            self._authorized, self._region_approved, self._phi_contract_approved
        )):
            raise RuntimeError(
                "Azure Read disabled: PHI contract, deployment region, and provider "
                "authorization must all be approved"
            )
        if self._backend is None:
            raise RuntimeError("Azure Read backend is not configured")
        started = time.perf_counter()
        stream = io.BytesIO()
        request.image.convert("RGB").save(stream, format="PNG")
        evidence = self._backend.analyze(stream.getvalue())
        return [OCRCandidate(
            value=evidence.text.strip() or None,
            raw_value=evidence.text,
            engine=self.engine_name,
            model_name=self.model_name,
            model_version=self.model_version,
            preprocessing_variant="original_regional_crop",
            raw_confidence=evidence.confidence,
            calibrated_confidence=None,
            bounding_box=request.bounding_box,
            latency_ms=(time.perf_counter() - started) * 1000,
            validation_results=(
                "SHADOW_REVIEW_ONLY",
                "HANDWRITTEN_STYLE" if evidence.handwritten else "PRINTED_STYLE",
            ),
        )]
