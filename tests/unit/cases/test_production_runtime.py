"""Production runtime fail-closed validation tests."""

from __future__ import annotations

import pytest

from packages.production_runtime import (
    PRODUCTION_RUNTIME_PROFILE_PATH,
    assert_production_ready,
    is_production_env,
    load_production_runtime_profile,
    validate_production_settings,
)
from packages.settings import Settings


def test_production_runtime_profile_hashes_verify():
    profile, payload = load_production_runtime_profile()
    assert profile.profile_id == "cdp-runtime-decision-production"
    assert payload["pipeline_release"] == "extraction-v2"
    assert payload["fail_closed"]["shadow_review_only_cannot_auto"] is True
    assert PRODUCTION_RUNTIME_PROFILE_PATH.is_file()


def test_non_production_env_skips_settings_gate(monkeypatch):
    monkeypatch.delenv("CDP_ENV", raising=False)
    assert not is_production_env()
    # Local sqlite + in-memory bus must still be allowed outside production.
    result = assert_production_ready(
        Settings(
            database_url="sqlite:///:memory:",
            use_in_memory_bus=True,
        )
    )
    assert result.ok


def test_production_env_rejects_sqlite_and_in_memory_bus(monkeypatch):
    monkeypatch.setenv("CDP_ENV", "production")
    result = validate_production_settings(
        Settings(
            database_url="sqlite:///:memory:",
            use_in_memory_bus=True,
            object_store_access_key="minioadmin",
            object_store_secret_key="minioadmin",
        )
    )
    codes = {i.code for i in result.issues}
    assert "SQLITE_FORBIDDEN" in codes
    assert "IN_MEMORY_BUS_FORBIDDEN" in codes
    assert "DEFAULT_MINIO_CREDENTIALS_FORBIDDEN" in codes
    assert not result.ok


def test_production_env_rejects_unapproved_ai_gateway():
    result = validate_production_settings(
        Settings(
            database_url="mysql+pymysql://idp:secret@db:3306/idp",
            use_in_memory_bus=False,
            object_store_access_key="prod-key",
            object_store_secret_key="prod-secret",
            ai_gateway_enabled=True,
            ai_phi_external_processing_approved=False,
        )
    )
    assert any(i.code == "AI_GATEWAY_REQUIRES_PHI_APPROVAL" for i in result.issues)


def test_production_env_rejects_azure_di_without_gates():
    result = validate_production_settings(
        Settings(
            database_url="mysql+pymysql://idp:secret@db:3306/idp",
            use_in_memory_bus=False,
            object_store_access_key="prod-key",
            object_store_secret_key="prod-secret",
            azure_document_intelligence_enabled=True,
            azure_document_intelligence_authorized=False,
            azure_document_intelligence_review_only=False,
        )
    )
    codes = {i.code for i in result.issues}
    assert "AZURE_DI_REQUIRES_AUTH_GATES" in codes
    assert "AZURE_DI_MUST_STAY_REVIEW_ONLY" in codes


def test_production_env_accepts_hardened_defaults():
    result = validate_production_settings(
        Settings(
            database_url="mysql+pymysql://idp:secret@db:3306/idp",
            use_in_memory_bus=False,
            object_store_access_key="prod-key",
            object_store_secret_key="prod-secret",
            vlm_enabled=False,
            ai_gateway_enabled=False,
            azure_document_intelligence_enabled=False,
            azure_ai_evaluation_enabled=False,
            azure_openai_review_only=True,
        )
    )
    assert result.ok
    assert result.issues == ()


def test_production_env_still_accepts_postgres():
    result = validate_production_settings(
        Settings(
            database_url="postgresql+psycopg://idp:secret@db:5432/idp",
            use_in_memory_bus=False,
            object_store_access_key="prod-key",
            object_store_secret_key="prod-secret",
        )
    )
    assert result.ok


def test_assert_production_ready_raises_in_prod(monkeypatch):
    monkeypatch.setenv("CDP_ENV", "prod")
    with pytest.raises(RuntimeError, match="PRODUCTION_RUNTIME_INVALID"):
        assert_production_ready(
            Settings(
                database_url="sqlite:///:memory:",
                use_in_memory_bus=True,
            )
        )
