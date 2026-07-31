"""Production construction for the crop-only, review-gated escalation path."""

from __future__ import annotations

from packages.settings import Settings
from workers.unstructured_extraction.escalation import UnstructuredFieldEscalator
from workers.vlm_fallback.factory import build_azure_review_adapter
from workers.vlm_fallback.service import VLMFallbackService


def build_production_escalator(settings: Settings) -> UnstructuredFieldEscalator:
    if not settings.azure_ai_evaluation_enabled:
        return UnstructuredFieldEscalator()
    adapter = build_azure_review_adapter(settings)
    return UnstructuredFieldEscalator(
        vlm=VLMFallbackService(
            adapter,
            model_name=settings.azure_ai_evaluation_deployment or "azure-openai",
            model_version=f"azure-api-{settings.azure_openai_api_version}",
        )
    )
