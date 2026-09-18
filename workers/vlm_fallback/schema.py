"""Re-export VLM schema from packages for back-compat.

Canonical definitions live in ``packages.vlm_schema`` so packages never need
to import workers for request/response types.
"""

from __future__ import annotations

from packages.vlm_schema import (
    VLMFieldRequest,
    VLMFieldResult,
    build_response_json_schema,
)

__all__ = [
    "VLMFieldRequest",
    "VLMFieldResult",
    "build_response_json_schema",
]
