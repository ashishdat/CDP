import json

import httpx

from workers.vlm_fallback.adapter import AzureOpenAIVisionAdapter
from workers.vlm_fallback.schema import VLMFieldRequest


def test_azure_adapter_uses_crop_only_strict_request_without_leaking_key():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["header"] = request.headers["api-key"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({"fields": [{
                "field_name": "description", "value": "Ancillary Code Detox",
                "confidence": 0.91, "insufficient_evidence": False,
                "citation": "visible crop text",
            }]})}}]
        })

    adapter = AzureOpenAIVisionAdapter(
        endpoint="https://example.openai.azure.com", deployment="vision",
        api_version="2025-01-01-preview", api_key="test-secret", enabled=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.extract_fields(
        {"description": b"png-bytes"},
        [VLMFieldRequest(
            field_name="description", field_type="text",
            expected_description="UB04 FL43", prior_ocr_candidates=["Ancillarv"],
        )],
    )
    assert result[0].value == "Ancillary Code Detox"
    assert captured["header"] == "test-secret"
    assert "api-key" not in json.dumps(captured["payload"]).lower()
    content = captured["payload"]["messages"][0]["content"]
    assert sum(part["type"] == "image_url" for part in content) == 1
    assert captured["payload"]["temperature"] == 0
