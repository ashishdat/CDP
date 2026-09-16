"""Fail-closed construction of Azure Document Intelligence Read engines."""

from __future__ import annotations

from packages.settings import Settings
from workers.cascade.azure_di_backend import (
    AzureDocumentIntelligenceReadBackend,
    azure_di_handwriting_transport,
)
from workers.cascade.azure_read_adapter import AzureReadShadowEngine
from workers.unstructured_extraction.cloud_handwriting import CropOnlyCloudProvider


class AzureDocumentIntelligenceConfigurationError(RuntimeError):
    pass


def _di_endpoint(settings: Settings) -> str | None:
    return settings.azure_document_intelligence_endpoint or settings.cloud_handwriting_endpoint


def _di_key(settings: Settings) -> str | None:
    return settings.azure_document_intelligence_api_key or settings.cloud_handwriting_credential


def azure_document_intelligence_configured(settings: Settings) -> bool:
    return bool(
        settings.azure_document_intelligence_enabled
        and _di_endpoint(settings)
        and _di_key(settings)
        and settings.azure_document_intelligence_authorized
        and settings.azure_document_intelligence_region_approved
        and settings.azure_document_intelligence_phi_contract_approved
    )


def build_azure_read_engine(settings: Settings) -> AzureReadShadowEngine:
    if not settings.azure_document_intelligence_enabled:
        raise AzureDocumentIntelligenceConfigurationError("Azure Document Intelligence is disabled")
    endpoint = _di_endpoint(settings)
    api_key = _di_key(settings)
    missing = [
        name
        for name, value in {
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": endpoint,
            "AZURE_DOCUMENT_INTELLIGENCE_API_KEY": api_key,
        }.items()
        if not value
    ]
    if missing:
        raise AzureDocumentIntelligenceConfigurationError(
            f"missing Azure Document Intelligence configuration: {', '.join(missing)}"
        )
    if not all(
        (
            settings.azure_document_intelligence_authorized,
            settings.azure_document_intelligence_region_approved,
            settings.azure_document_intelligence_phi_contract_approved,
        )
    ):
        raise AzureDocumentIntelligenceConfigurationError(
            "Azure DI requires PHI contract, region, and provider authorization"
        )
    backend = AzureDocumentIntelligenceReadBackend(
        endpoint or "",
        api_key or "",
        api_version=settings.azure_document_intelligence_api_version,
        timeout_seconds=settings.cloud_handwriting_timeout_seconds,
    )
    return AzureReadShadowEngine(
        backend=backend,
        authorized=True,
        region_approved=True,
        phi_contract_approved=True,
        provider_version=settings.azure_document_intelligence_api_version,
    )


def build_azure_di_cloud_handwriting_provider(settings: Settings) -> CropOnlyCloudProvider:
    """Crop-only handwriting provider backed by Azure DI prebuilt-read."""
    endpoint = _di_endpoint(settings)
    credential = _di_key(settings)
    enabled = bool(
        settings.cloud_handwriting_enabled
        or settings.azure_document_intelligence_enabled
    )
    api_version = settings.azure_document_intelligence_api_version

    def _transport(**kwargs):
        kwargs.setdefault("api_version", api_version)
        return azure_di_handwriting_transport(**kwargs)

    return CropOnlyCloudProvider(
        provider="azure_document_intelligence_read",
        endpoint=endpoint,
        credential=credential,
        transport=_transport,
        enabled=enabled and azure_document_intelligence_configured(settings),
        timeout_seconds=settings.cloud_handwriting_timeout_seconds,
    )
