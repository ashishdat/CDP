"""Production close-out evidence package: init + fail-closed validation.

Scaffolds operator evidence under ``evaluation_results/production_closeout/``
and evaluates it with ``ProductionReadinessGate`` plus organizational
approval flags. Does **not** invent holdout metrics or authorize PHI.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.production_readiness_gate import (
    ProductionReadinessGate,
    ReadinessDecision,
    ReadinessEvidence,
    ReadinessResult,
)
from packages.runtime_profile.contracts import ROOT

TEMPLATE_DIR = ROOT / "docs" / "templates"
EVIDENCE_TEMPLATE = TEMPLATE_DIR / "production_promotion_evidence.template.json"
ATTESTATION_TEMPLATE = TEMPLATE_DIR / "holdout_attestation.template.json"
LAUNCH_RECORD_TEMPLATE = TEMPLATE_DIR / "PRODUCTION_LAUNCH_RECORD.md"
DEFAULT_PACKAGE_DIR = ROOT / "evaluation_results" / "production_closeout"

REQUIRED_ORG_FLAGS = (
    "idp_rbac_passed",
    "baa_phi_contract_passed",
    "region_retention_keys_passed",
    "security_assessment_passed",
    "data_governance_attestation_passed",
    "staging_cluster_passed",
    "database_restore_drill_passed",
    "signed_promotion",
)


@dataclass(frozen=True)
class CloseoutIssue:
    code: str
    message: str


@dataclass(frozen=True)
class CloseoutValidation:
    ok: bool
    decision: ReadinessDecision
    gate_result: ReadinessResult
    issues: tuple[CloseoutIssue, ...]
    package_dir: Path

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision": self.decision.value,
            "blocking_reasons": list(self.gate_result.blocking_reasons),
            "issues": [{"code": i.code, "message": i.message} for i in self.issues],
            "package_dir": str(self.package_dir),
        }


def init_closeout_package(package_dir: Path | None = None) -> Path:
    """Copy templates into a working evidence package (idempotent for missing files)."""
    target = package_dir or DEFAULT_PACKAGE_DIR
    target.mkdir(parents=True, exist_ok=True)

    evidence_path = target / "evidence.json"
    if not evidence_path.exists():
        shutil.copyfile(EVIDENCE_TEMPLATE, evidence_path)

    attestation_path = target / "holdout_attestation.json"
    if not attestation_path.exists():
        shutil.copyfile(ATTESTATION_TEMPLATE, attestation_path)

    launch_path = target / "LAUNCH_RECORD.md"
    if not launch_path.exists():
        shutil.copyfile(LAUNCH_RECORD_TEMPLATE, launch_path)

    checklist_src = ROOT / "docs" / "PRODUCTION_CLOSEOUT_CHECKLIST.md"
    checklist_dst = target / "CHECKLIST.md"
    if checklist_src.is_file() and not checklist_dst.exists():
        shutil.copyfile(checklist_src, checklist_dst)

    readme = target / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Production close-out package\n\n"
            "1. Follow `CHECKLIST.md`.\n"
            "2. Fill `holdout_attestation.json` and freeze holdout with "
            "`evaluation.untouched_holdout.UntouchedHoldoutBuilder`.\n"
            "3. Fill measured metrics in `evidence.json` "
            "(never invent numbers).\n"
            "4. Complete `LAUNCH_RECORD.md` and set org approval flags.\n"
            "5. Run `python3 scripts/check_production_closeout.py`.\n\n"
            "Exit 0 + `PROMOTE_TO_PRODUCTION` is required before labeling "
            "the environment production-authorized.\n",
            encoding="utf-8",
        )
    return target


def load_evidence_package(package_dir: Path | None = None) -> dict[str, Any]:
    target = package_dir or DEFAULT_PACKAGE_DIR
    path = target / "evidence.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing evidence package at {path}; run with --init first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _org_issues(approvals: dict[str, Any]) -> list[CloseoutIssue]:
    issues: list[CloseoutIssue] = []
    for flag in REQUIRED_ORG_FLAGS:
        if not approvals.get(flag):
            issues.append(
                CloseoutIssue(
                    f"ORG_{flag.upper()}",
                    f"organizational approval '{flag}' is not true",
                )
            )
    if not (approvals.get("incident_owner") or "").strip():
        issues.append(
            CloseoutIssue("ORG_INCIDENT_OWNER", "incident_owner is required")
        )
    if not (approvals.get("rollback_decision_maker") or "").strip():
        issues.append(
            CloseoutIssue(
                "ORG_ROLLBACK_OWNER",
                "rollback_decision_maker is required",
            )
        )
    return issues


def _canary_issues(canary: dict[str, Any]) -> list[CloseoutIssue]:
    issues: list[CloseoutIssue] = []
    if not canary.get("completed"):
        issues.append(
            CloseoutIssue("CANARY_INCOMPLETE", "canary.completed must be true")
        )
    if not (canary.get("scope_description") or "").strip():
        issues.append(
            CloseoutIssue("CANARY_SCOPE", "canary.scope_description is required")
        )
    fa = canary.get("critical_false_accepts_observed")
    if fa is None:
        issues.append(
            CloseoutIssue(
                "CANARY_FA_MISSING",
                "canary.critical_false_accepts_observed is required",
            )
        )
    elif fa != 0:
        issues.append(
            CloseoutIssue(
                "CANARY_CRITICAL_FA",
                "canary observed critical false accepts; cannot promote",
            )
        )
    return issues


def validate_closeout_package(
    package_dir: Path | None = None,
    *,
    gate: ProductionReadinessGate | None = None,
) -> CloseoutValidation:
    """Fail-closed validation of the operator evidence package."""
    target = package_dir or DEFAULT_PACKAGE_DIR
    payload = load_evidence_package(target)
    issues: list[CloseoutIssue] = []

    config = payload.get("configuration") or {}
    if not config.get("holdout_manifest_path"):
        issues.append(
            CloseoutIssue(
                "HOLDOUT_MANIFEST_PATH",
                "configuration.holdout_manifest_path is required",
            )
        )
    if not config.get("holdout_manifest_sha256"):
        issues.append(
            CloseoutIssue(
                "HOLDOUT_MANIFEST_HASH",
                "configuration.holdout_manifest_sha256 is required",
            )
        )
    if not config.get("application_commit_sha"):
        issues.append(
            CloseoutIssue(
                "APPLICATION_COMMIT",
                "configuration.application_commit_sha is required",
            )
        )

    issues.extend(_org_issues(payload.get("organizational_approvals") or {}))
    issues.extend(_canary_issues(payload.get("canary") or {}))

    readiness_raw = payload.get("readiness_evidence") or {}
    evidence = ReadinessEvidence.model_validate(readiness_raw)
    gate_obj = gate or ProductionReadinessGate.load()
    gate_result = gate_obj.evaluate(evidence)

    # Mirror org approvals into gate-facing security/db/load when claimed.
    # The readiness gate still requires measured holdout metrics separately.
    if gate_result.decision is not ReadinessDecision.PROMOTE_TO_PRODUCTION:
        issues.append(
            CloseoutIssue(
                "READINESS_GATE",
                f"readiness gate decision is {gate_result.decision.value}; "
                f"blocking={gate_result.blocking_reasons}",
            )
        )

    ok = not issues and gate_result.decision is ReadinessDecision.PROMOTE_TO_PRODUCTION
    return CloseoutValidation(
        ok=ok,
        decision=gate_result.decision,
        gate_result=gate_result,
        issues=tuple(issues),
        package_dir=target,
    )


def write_validation_report(
    validation: CloseoutValidation,
    *,
    path: Path | None = None,
) -> Path:
    target = path or (validation.package_dir / "validation_report.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(validation.summary(), indent=2) + "\n",
        encoding="utf-8",
    )
    return target
