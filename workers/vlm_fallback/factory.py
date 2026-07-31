"""Fail-closed construction of the production Azure crop-only adapter."""

from __future__ import annotations

from packages.settings import Settings
from workers.vlm_fallback.adapter import AzureOpenAIVisionAdapter


class AzureProductionConfigurationError(RuntimeError):
    pass


def build_azure_review_adapter(settings: Settings) -> AzureOpenAIVisionAdapter:
    if not settings.azure_ai_evaluation_enabled:
        raise AzureProductionConfigurationError("Azure crop fallback is disabled")
    if not settings.azure_openai_review_only:
        raise AzureProductionConfigurationError(
            "automatic Azure acceptance is blocked pending untouched holdout evidence"
        )
    required = {
        "AZURE_OPENAI_ENDPOINT": settings.azure_openai_endpoint,
        "AZURE_OPENAI_API_KEY": settings.azure_openai_api_key,
        "AZURE_AI_EVALUATION_DEPLOYMENT": settings.azure_ai_evaluation_deployment,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise AzureProductionConfigurationError(
            f"missing Azure production configuration: {', '.join(missing)}"
        )
    return AzureOpenAIVisionAdapter(
        endpoint=settings.azure_openai_endpoint or "",
        deployment=settings.azure_ai_evaluation_deployment or "",
        api_version=settings.azure_openai_api_version,
        api_key=settings.azure_openai_api_key or "",
        enabled=True,
    )
