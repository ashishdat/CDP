"""Compact VLM fallback: crop-only input, temperature 0, strict JSON,
disabled by default (`VLM_ENABLED=false`). See adapter.py for the full
list of enforced safety properties."""

from workers.vlm_fallback.adapter import (
    OpenAIVLLMAdapter,
    VLMAdapter,
    VLMDisabledError,
    VLMResponseError,
)
from workers.vlm_fallback.schema import (
    VLMFieldRequest,
    VLMFieldResult,
    build_response_json_schema,
)
from workers.vlm_fallback.service import VLMFallbackService

__all__ = [
    "OpenAIVLLMAdapter",
    "VLMAdapter",
    "VLMDisabledError",
    "VLMFallbackService",
    "VLMFieldRequest",
    "VLMFieldResult",
    "VLMResponseError",
    "build_response_json_schema",
]
