"""Production construction for the crop-only, review-gated escalation path."""

from __future__ import annotations

from packages.settings import Settings
from workers.unstructured_extraction.escalation import UnstructuredFieldEscalator
from workers.vlm_fallback.factory import (
    AzureProductionConfigurationError,
    build_azure_review_adapter,
    build_vlm_fallback_adapter,
)
from workers.vlm_fallback.service import VLMFallbackService


def build_production_escalator(settings: Settings) -> UnstructuredFieldEscalator:
    """Prefer Azure gpt-4o review cascade when configured; else local VLM; else no-op."""
    if settings.azure_ai_evaluation_enabled:
        try:
            adapter = build_azure_review_adapter(settings)
            return UnstructuredFieldEscalator(
                vlm=VLMFallbackService(
                    adapter,
                    model_name=settings.azure_ai_evaluation_deployment or "gpt-4o",
                    model_version="azure-review-only",
                )
            )
        except AzureProductionConfigurationError:
            # Fail closed to local/no-op rather than crash the common path.
            pass
    if not settings.vlm_enabled:
        return UnstructuredFieldEscalator()
    adapter = build_vlm_fallback_adapter(settings)
    return UnstructuredFieldEscalator(
        vlm=VLMFallbackService(
            adapter,
            model_name=settings.vlm_model_name,
            model_version="1.0",
        )
    )
