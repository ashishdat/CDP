import json
from io import BytesIO

from PIL import Image

from packages.settings import Settings
from workers.cascade.azure_di_backend import AzureDocumentIntelligenceReadBackend
from workers.cascade.azure_di_factory import (
    AzureDocumentIntelligenceConfigurationError,
    azure_document_intelligence_configured,
    build_azure_read_engine,
)
from workers.cascade.azure_read_adapter import AzureReadEvidence


class _FakeResponse:
    def __init__(self, *, headers=None, body=b"", status=200):
        self.headers = headers or {}
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_azure_di_backend_polls_prebuilt_read():
    calls: list[str] = []

    def opener(request, timeout=30):
        calls.append(request.full_url if hasattr(request, "full_url") else request.get_full_url())
        if request.get_method() == "POST":
            return _FakeResponse(
                headers={"Operation-Location": "https://di.example/ops/1"},
            )
        payload = {
            "status": "succeeded",
            "analyzeResult": {
                "content": "01/15/1966",
                "styles": [{"isHandwritten": True}],
                "pages": [{"words": [{"content": "01/15/1966", "confidence": 0.92}]}],
            },
        }
        return _FakeResponse(body=json.dumps(payload).encode("utf-8"))

    backend = AzureDocumentIntelligenceReadBackend(
        "https://di.example",
        "secret",
        opener=opener,
        poll_interval_seconds=0,
    )
    evidence = backend.analyze(b"\x89PNG")
    assert isinstance(evidence, AzureReadEvidence)
    assert evidence.text == "01/15/1966"
    assert evidence.handwritten is True
    assert evidence.confidence == 0.92
    assert any("prebuilt-read:analyze" in url for url in calls)


def test_factory_fails_closed_without_gates():
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_enabled=True,
        azure_document_intelligence_endpoint="https://di.example",
        azure_document_intelligence_api_key="secret",
        azure_document_intelligence_authorized=False,
    )
    assert azure_document_intelligence_configured(settings) is False
    try:
        build_azure_read_engine(settings)
    except AzureDocumentIntelligenceConfigurationError as exc:
        assert "authorization" in str(exc).lower() or "PHI" in str(exc)
    else:
        raise AssertionError("expected fail-closed configuration error")


def test_factory_builds_when_phi_gates_approved():
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_enabled=True,
        azure_document_intelligence_endpoint="https://di.example",
        azure_document_intelligence_api_key="secret",
        azure_document_intelligence_authorized=True,
        azure_document_intelligence_region_approved=True,
        azure_document_intelligence_phi_contract_approved=True,
    )
    assert azure_document_intelligence_configured(settings) is True
    engine = build_azure_read_engine(settings)
    assert engine.engine_name == "azure_document_intelligence_read"
    assert engine.model_name == "prebuilt-read"
