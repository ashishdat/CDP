"""Compact VLM fallback: crop-only input, temperature 0, strict JSON,
disabled by default (`VLM_ENABLED=false`). See adapter.py for the full
list of enforced safety properties."""

from workers.vlm_fallback.adapter import (
    AzureOpenAIVisionAdapter,
    OpenAIVLLMAdapter,
    VLMAdapter,
    VLMDisabledError,
    VLMResponseError,
)
from workers.vlm_fallback.factory import (
    AzureProductionConfigurationError,
    build_azure_review_adapter,
)
from workers.vlm_fallback.schema import (
    VLMFieldRequest,
    VLMFieldResult,
    build_response_json_schema,
)
from workers.vlm_fallback.service import VLMFallbackService

__all__ = [
    "AzureOpenAIVisionAdapter",
    "AzureProductionConfigurationError",
    "OpenAIVLLMAdapter",
    "VLMAdapter",
    "VLMDisabledError",
    "VLMFallbackService",
    "VLMFieldRequest",
    "VLMFieldResult",
    "VLMResponseError",
    "build_azure_review_adapter",
    "build_response_json_schema",
]
