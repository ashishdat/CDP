"""Anthropic Claude Sonnet vision crop adapter tests (no live network)."""

from __future__ import annotations

import base64
import json

import httpx

from packages.vlm_schema import VLMFieldRequest
from workers.vlm_fallback.adapter import AnthropicClaudeVisionAdapter, VLMResponseError


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.last_request: httpx.Request | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        return httpx.Response(
            self.status,
            json=self.payload,
            request=request,
        )


def test_anthropic_claude_adapter_parses_json_fields():
    transport = _FakeTransport(
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "fields": [
                                {
                                    "field_name": "total_charge",
                                    "value": "222.22",
                                    "confidence": 0.91,
                                    "insufficient_evidence": False,
                                    "citation": None,
                                }
                            ]
                        }
                    ),
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )
    client = httpx.Client(transport=transport)
    adapter = AnthropicClaudeVisionAdapter(
        api_key="test-key",
        model="claude-sonnet-4-20250514",
        enabled=True,
        http_client=client,
    )
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    results = adapter.extract_fields(
        {"total_charge": png},
        [
            VLMFieldRequest(
                field_name="total_charge",
                field_type="currency",
                expected_description="Box 28 total",
                prior_ocr_candidates=["2221.22"],
            )
        ],
    )
    assert len(results) == 1
    assert results[0].value == "222.22"
    assert results[0].insufficient_evidence is False
    assert adapter.last_usage["total_tokens"] == 15
    assert transport.last_request is not None
    assert transport.last_request.url.path.endswith("/v1/messages")
    assert transport.last_request.headers["x-api-key"] == "test-key"
    body = json.loads(transport.last_request.content)
    assert body["model"] == "claude-sonnet-4-20250514"
    assert body["temperature"] == 0


def test_anthropic_claude_adapter_surfaces_api_errors():
    transport = _FakeTransport(
        {"error": {"type": "authentication_error", "message": "invalid x-api-key"}},
        status=401,
    )
    adapter = AnthropicClaudeVisionAdapter(
        api_key="bad",
        enabled=True,
        http_client=httpx.Client(transport=transport),
    )
    try:
        adapter.extract_fields(
            {"patient_name": b"abc"},
            [
                VLMFieldRequest(
                    field_name="patient_name",
                    field_type="text",
                    expected_description="name",
                )
            ],
        )
        assert False, "expected VLMResponseError"
    except VLMResponseError as exc:
        assert "401" in str(exc)
