"""The VLM's request/response contract. `VLMFieldResult` uses
`extra="forbid"` and the JSON schema sent to the model sets
`additionalProperties: false` -- "prohibit unsupported fields" is enforced
at both the schema-we-send and the response-we-parse layer, not just
documented intent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VLMFieldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    field_type: str  # text | date | currency | code | npi | tax_id | checkbox
    expected_description: str
    prior_ocr_candidates: list[str] = Field(default_factory=list)


class VLMFieldResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    value: str | None
    confidence: float = Field(ge=0, le=1)
    insufficient_evidence: bool = False
    citation: str | None = None


def build_response_json_schema(field_names: list[str]) -> dict[str, Any]:
    """A strict JSON schema for OpenAI/vLLM structured-output mode: an
    object with exactly one `fields` array, each entry constrained to the
    same shape as `VLMFieldResult`, `additionalProperties: false`
    everywhere. `field_names` isn't used to generate a name enum here
    (structured-output schemas are the same regardless of which fields
    were requested) -- the requested-vs-returned check happens in
    `adapter.py` after parsing, where we have both sides to compare."""
    del field_names  # reserved for a future per-request enum constraint
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["fields"],
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field_name", "value", "confidence", "insufficient_evidence"],
                    "properties": {
                        "field_name": {"type": "string"},
                        "value": {"type": ["string", "null"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "insufficient_evidence": {"type": "boolean"},
                        "citation": {"type": ["string", "null"]},
                    },
                },
            }
        },
    }
