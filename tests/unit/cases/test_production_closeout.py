"""Tests for production close-out evidence package init + validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.production_closeout import (
    init_closeout_package,
    validate_closeout_package,
)
from packages.production_readiness_gate import ReadinessDecision


def _passing_evidence_payload() -> dict:
    return {
        "schema_version": "production-promotion-evidence-v1",
        "status": "COMPLETE",
        "configuration": {
            "pipeline_release": "extraction-v2",
            "runtime_profile": "config/runtime_profiles/production_runtime_v1.yaml",
            "readiness_gate": "config/production_readiness_gate.yaml",
            "holdout_policy": "config/production_holdout_policy.yaml",
            "application_commit_sha": "abc123",
            "holdout_manifest_path": "evaluation_data/holdouts/PRODUCTION_HOLDOUT_V1/manifest.json",
            "holdout_manifest_sha256": "0" * 64,
        },
        "organizational_approvals": {
            "idp_rbac_passed": True,
            "baa_phi_contract_passed": True,
            "region_retention_keys_passed": True,
            "security_assessment_passed": True,
            "data_governance_attestation_passed": True,
            "staging_cluster_passed": True,
            "database_restore_drill_passed": True,
            "signed_promotion": True,
            "incident_owner": "ops@example.com",
            "rollback_decision_maker": "release@example.com",
            "approver_references": {"ticket": "SEC-1"},
        },
        "readiness_evidence": {
            "holdout_frozen": True,
            "holdout_independent": True,
            "holdout_documents": 5000,
            "holdout_fields": 15000,
            "full_suite_passed": True,
            "overall_raw_accuracy": 0.96,
            "critical_accuracy": 0.99,
            "total_false_accept_rate": 0.0,
            "critical_false_accept_count": 0,
            "safe_field_coverage": 0.95,
            "claim_stp": 0.95,
            "claim_hitl": 0.05,
            "claim_hitl_count": 250,
            "accepted_critical_field_decisions": 4000,
            "critical_accepted_precision": 0.999,
            "wrong_crop_recall": 0.97,
            "maximum_segment_claim_hitl": 0.10,
            "p95_latency_ms": 1000,
            "cost_per_document_usd": 0.01,
            "runtime_parity_passed": True,
            "route_governance_passed": True,
            "security_passed": True,
            "database_and_events_passed": True,
            "load_and_keda_passed": True,
            "shadow_validation_passed": True,
            "failure_injection_passed": True,
        },
        "canary": {
            "scope_description": "1% of tenant demo for 7 days",
            "shadow_samples": 2000,
            "critical_false_accepts_observed": 0,
            "completed": True,
        },
    }


def test_init_creates_package(tmp_path: Path):
    path = init_closeout_package(tmp_path / "closeout")
    assert (path / "evidence.json").is_file()
    assert (path / "holdout_attestation.json").is_file()
    assert (path / "LAUNCH_RECORD.md").is_file()
    assert (path / "CHECKLIST.md").is_file()
    assert (path / "README.md").is_file()


def test_incomplete_package_fails_closed(tmp_path: Path):
    path = init_closeout_package(tmp_path / "closeout")
    result = validate_closeout_package(path)
    assert not result.ok
    assert result.decision is ReadinessDecision.NEEDS_MORE_DATA
    codes = {i.code for i in result.issues}
    assert "ORG_IDP_RBAC_PASSED" in codes
    assert "HOLDOUT_MANIFEST_PATH" in codes
    assert "READINESS_GATE" in codes


def test_complete_package_promotes(tmp_path: Path):
    path = tmp_path / "closeout"
    path.mkdir()
    (path / "evidence.json").write_text(
        json.dumps(_passing_evidence_payload()), encoding="utf-8"
    )
    result = validate_closeout_package(path)
    assert result.ok
    assert result.decision is ReadinessDecision.PROMOTE_TO_PRODUCTION
    assert result.issues == ()


def test_canary_false_accept_blocks(tmp_path: Path):
    path = tmp_path / "closeout"
    path.mkdir()
    payload = _passing_evidence_payload()
    payload["canary"]["critical_false_accepts_observed"] = 1
    (path / "evidence.json").write_text(json.dumps(payload), encoding="utf-8")
    result = validate_closeout_package(path)
    assert not result.ok
    assert any(i.code == "CANARY_CRITICAL_FA" for i in result.issues)
