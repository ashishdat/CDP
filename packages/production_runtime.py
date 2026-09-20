"""Production runtime fail-closed validation.

When ``CDP_ENV=production`` (or ``prod``), refuse unsafe local defaults:
in-memory bus, sqlite, missing object-store credentials, and external AI
without authorization gates. REVIEW_ONLY shadows must remain review-only.

This does **not** authorize PHI processing — see docs/PRODUCTION_READINESS.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from packages.runtime_profile.contracts import (
    ROOT,
    RuntimeDecisionProfile,
    canonical_file_sha256,
)
from packages.settings import Settings

PRODUCTION_RUNTIME_PROFILE_PATH = (
    ROOT / "config/runtime_profiles/production_runtime_v1.yaml"
)


def is_production_env(raw: str | None = None) -> bool:
    text = (raw if raw is not None else os.environ.get("CDP_ENV") or "").strip().casefold()
    return text in {"production", "prod"}


@dataclass(frozen=True)
class ProductionValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ProductionValidationResult:
    ok: bool
    issues: tuple[ProductionValidationIssue, ...]

    def raise_if_invalid(self) -> None:
        if self.ok:
            return
        detail = "; ".join(f"{i.code}: {i.message}" for i in self.issues)
        raise RuntimeError(f"PRODUCTION_RUNTIME_INVALID: {detail}")


def _looks_like_sqlite(url: str) -> bool:
    lowered = (url or "").strip().casefold()
    return lowered.startswith("sqlite:") or ":memory:" in lowered


def _looks_like_default_minio(access_key: str, secret_key: str) -> bool:
    return access_key == "minioadmin" and secret_key == "minioadmin"


def validate_production_settings(settings: Settings) -> ProductionValidationResult:
    """Fail-closed checks for CDP_ENV=production."""
    issues: list[ProductionValidationIssue] = []

    if settings.use_in_memory_bus:
        issues.append(
            ProductionValidationIssue(
                "IN_MEMORY_BUS_FORBIDDEN",
                "USE_IN_MEMORY_BUS must be false in production",
            )
        )
    if _looks_like_sqlite(settings.database_url):
        issues.append(
            ProductionValidationIssue(
                "SQLITE_FORBIDDEN",
                "DATABASE_URL must be Postgres (or equivalent) in production",
            )
        )
    if not (settings.object_store_access_key and settings.object_store_secret_key):
        issues.append(
            ProductionValidationIssue(
                "OBJECT_STORE_CREDENTIALS_REQUIRED",
                "OBJECT_STORE_ACCESS_KEY/SECRET_KEY required in production",
            )
        )
    if _looks_like_default_minio(
        settings.object_store_access_key, settings.object_store_secret_key
    ):
        issues.append(
            ProductionValidationIssue(
                "DEFAULT_MINIO_CREDENTIALS_FORBIDDEN",
                "Replace default minioadmin credentials before production",
            )
        )
    if settings.vlm_enabled:
        issues.append(
            ProductionValidationIssue(
                "VLM_MUST_STAY_OFF_UNTIL_APPROVED",
                "VLM_ENABLED must remain false until holdout/BAA approval",
            )
        )
    if settings.ai_gateway_enabled and not settings.ai_phi_external_processing_approved:
        issues.append(
            ProductionValidationIssue(
                "AI_GATEWAY_REQUIRES_PHI_APPROVAL",
                "AI_GATEWAY_ENABLED requires AI_PHI_EXTERNAL_PROCESSING_APPROVED",
            )
        )
    if settings.azure_document_intelligence_enabled:
        if not (
            settings.azure_document_intelligence_authorized
            and settings.azure_document_intelligence_region_approved
            and settings.azure_document_intelligence_phi_contract_approved
        ):
            issues.append(
                ProductionValidationIssue(
                    "AZURE_DI_REQUIRES_AUTH_GATES",
                    "Azure DI requires AUTHORIZED + REGION + PHI contract flags",
                )
            )
        if not settings.azure_document_intelligence_review_only:
            issues.append(
                ProductionValidationIssue(
                    "AZURE_DI_MUST_STAY_REVIEW_ONLY",
                    "AZURE_DOCUMENT_INTELLIGENCE_REVIEW_ONLY must be true until route promotion",
                )
            )
    if settings.azure_ai_evaluation_enabled and not settings.azure_openai_review_only:
        issues.append(
            ProductionValidationIssue(
                "AZURE_OPENAI_MUST_STAY_REVIEW_ONLY",
                "AZURE_OPENAI_REVIEW_ONLY must be true until holdout route promotion",
            )
        )
    if not settings.azure_openai_review_only and settings.azure_ai_evaluation_enabled:
        issues.append(
            ProductionValidationIssue(
                "SHADOW_REVIEW_ONLY_CANNOT_AUTO",
                "External OpenAI crop residuals cannot AUTO in production without promotion",
            )
        )

    return ProductionValidationResult(ok=not issues, issues=tuple(issues))


def load_production_runtime_profile(
    path: Path | None = None,
) -> tuple[RuntimeDecisionProfile, dict[str, Any]]:
    """Load + hash-verify the production runtime profile YAML."""
    target = path or PRODUCTION_RUNTIME_PROFILE_PATH
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    # RuntimeDecisionProfile forbids extra keys — strip production-only pins.
    decision_keys = {
        "profile_id",
        "profile_version",
        "profile_status",
        "route_mode",
        "created_at",
        "evidence_policy_path",
        "evidence_policy_sha256",
        "field_policy_path",
        "field_policy_sha256",
        "route_registry_path",
        "route_registry_sha256",
        "criticality_config_path",
        "criticality_config_sha256",
        "claim_policy_path",
        "claim_policy_sha256",
        "reference_config_path",
        "reference_config_sha256",
        "calibration_registry_path",
        "calibration_registry_sha256",
    }
    decision_payload = {k: payload[k] for k in decision_keys if k in payload}
    profile = RuntimeDecisionProfile.model_validate(decision_payload)
    profile.verify_hashes()

    release_path = payload.get("pipeline_release_manifest")
    release_sha = payload.get("pipeline_release_sha256")
    if release_path and release_sha:
        actual = canonical_file_sha256(ROOT / str(release_path))
        if actual != release_sha:
            raise ValueError(
                f"PRODUCTION_RELEASE_HASH_MISMATCH:{release_path}:{release_sha}:{actual}"
            )
    return profile, payload


def assert_production_ready(settings: Settings | None = None) -> ProductionValidationResult:
    """Validate settings when CDP_ENV=production; always verify profile hashes."""
    load_production_runtime_profile()
    if not is_production_env():
        return ProductionValidationResult(ok=True, issues=())
    result = validate_production_settings(settings or Settings())
    result.raise_if_invalid()
    return result
