"""Azure Document Intelligence contracts and injectable engine factory.

Pure settings checks and the configuration error live here so packages never
depend on the workers layer. The concrete Azure client is supplied via
``configure_azure_di_read_engine_factory`` from a composition root.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class AzureDocumentIntelligenceConfigurationError(RuntimeError):
    pass


def azure_document_intelligence_configured(settings: Any) -> bool:
    endpoint = (
        getattr(settings, "azure_document_intelligence_endpoint", None)
        or getattr(settings, "cloud_handwriting_endpoint", None)
    )
    api_key = (
        getattr(settings, "azure_document_intelligence_api_key", None)
        or getattr(settings, "cloud_handwriting_credential", None)
    )
    return bool(
        getattr(settings, "azure_document_intelligence_enabled", False)
        and endpoint
        and api_key
        and getattr(settings, "azure_document_intelligence_authorized", False)
        and getattr(settings, "azure_document_intelligence_region_approved", False)
        and getattr(settings, "azure_document_intelligence_phi_contract_approved", False)
    )


_build_azure_read_engine: Callable[[Any], Any] | None = None


def configure_azure_di_read_engine_factory(factory: Callable[[Any], Any]) -> None:
    """Composition root registers the concrete Azure DI Read engine builder."""
    global _build_azure_read_engine
    _build_azure_read_engine = factory


def build_azure_read_engine(settings: Any) -> Any:
    if _build_azure_read_engine is None:
        raise RuntimeError(
            "Azure DI read engine factory not configured; "
            "call configure_azure_di_read_engine_factory from composition root"
        )
    return _build_azure_read_engine(settings)
