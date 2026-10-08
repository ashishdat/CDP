"""Offline failure diagnosis and bounded recovery contracts for unseen samples.

Plans describe evidence acquisition; they cannot authorize acceptance or cloud I/O.
An empty OCR result never establishes that a page has no claim ink.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

VERSION = "independent-failure-recovery-v2"


class PageRole(StrEnum):
    CMS1500 = "CMS1500"
    UB04 = "UB04"
    CLAIM_FORM = "CLAIM_FORM"
    DOCUMENT_SEPARATOR = "DOCUMENT_SEPARATOR"
    FAX_PATCH = "FAX_PATCH"
    UNIQUE_ID_COVER = "UNIQUE_ID_COVER"
    EMPTY_OCR = "EMPTY_OCR"
    UNKNOWN = "UNKNOWN"


NON_CLAIM_CANDIDATES = frozenset({
    PageRole.DOCUMENT_SEPARATOR, PageRole.FAX_PATCH, PageRole.UNIQUE_ID_COVER,
})


def failure_category(row: Mapping[str, Any]) -> str:
    """Mutually exclusive root-stage categories, separate from terminal disposition."""
    disposition = str(row.get('disposition') or '')
    reason = str(row.get('registration_reason') or '')
    fallback = row.get('unstructured_reg_fallback') or {}
    if disposition == 'NOT_A_CLAIM_DOCUMENT' or fallback.get('reason') == 'MAILROOM_OR_FAX':
        return 'NON_CLAIM_PAGE'
    if (disposition in {'APP_FAILURE', 'STAGE_FAILURE', 'PIPELINE_FAILURE', 'OCR_FAILURE'}
            or 'TIMEOUT' in reason.upper() or reason in {'TEMPLATE_PROBE_BUDGET_EXHAUSTED', 'PAGE_ROUTING_PROBE_BUDGET_EXHAUSTED', 'REGISTRATION_RECOVERY_BUDGET_EXHAUSTED'} or row.get('error')):
        return 'RUNTIME_ERROR'
    if row.get('registration_ok') is False or disposition == 'REGISTRATION_FAILED':
        if reason in {'AMBIGUOUS_TEMPLATE', 'NO_CANDIDATES', 'EXPLICIT_TYPE_NO_TEMPLATE',
                      'NO_TEMPLATE_ABOVE_THRESHOLD', 'NO_QUALIFIED_TEMPLATE',
                      'REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE'}:
            return 'TEMPLATE_SELECTION_FAILURE'
        attempts = row.get('registration_attempt_count')
        if isinstance(attempts, int) and attempts > 0:
            return 'ALIGNMENT_FAILURE'
        if any(token in reason.lower() for token in (
            'insufficient_keypoints', 'insufficient_good_matches', 'insufficient_inliers',
            'low_inlier_ratio', 'low_coverage', 'unsafe_', 'invalid_transformed_corners',
        )):
            return 'ALIGNMENT_FAILURE'
        return 'UNCLASSIFIED_STAGE_FAILURE'
    return 'FIELD_REVIEW' if disposition == 'HITL' else 'NONE'


def classify_page_text(text: str | None) -> PageRole:
    text = text or ""
    if not text.strip():
        return PageRole.EMPTY_OCR
    # Claim evidence wins over separator/fax labels on mixed or attached pages.
    if re.search(r"UB[- ]?04|CMS[- ]?1450", text, re.IGNORECASE):
        return PageRole.UB04
    if re.search(r"CMS[- ]?1500|NUCC|HEALTH INSURANCE CLAIM", text, re.IGNORECASE):
        return PageRole.CMS1500
    if re.search(r"PATIENT\s*(?:'?S)?\s*NAME|BIRTH\s*DATE|DATE OF BIRTH|TOTAL\s*CHARGES?", text, re.IGNORECASE):
        return PageRole.CLAIM_FORM
    if re.search(r"fax\s*image|fax\s*patch|therefore\s+better", text, re.IGNORECASE):
        return PageRole.FAX_PATCH
    if re.search(r"unique\s*id|tracking\s*no", text, re.IGNORECASE):
        return PageRole.UNIQUE_ID_COVER
    if re.search(r"document\s*separator|00BREAK00|DOCSEP", text, re.IGNORECASE):
        return PageRole.DOCUMENT_SEPARATOR
    return PageRole.UNKNOWN


@dataclass(frozen=True)
class Finding:
    mechanism: str
    stage: str
    field_name: str | None
    evidence: tuple[str, ...]
    next_steps: tuple[str, ...]
    root_cause_status: str = "OBSERVED_MECHANISM_ONLY"
    max_attempts: int = 1


def analyze_failure(row: Mapping[str, Any], *, page_text: str | None = None,
                    page_role_verified: bool = False) -> dict[str, Any]:
    """Return value-free diagnoses. Ledger dispositions remain authoritative.

    A recovery always needs fresh evidence, the existing validation/decision
    gates and a terminal human route. No field value is copied into this report.
    """
    findings: list[Finding] = []
    role = classify_page_text(page_text) if page_text is not None else PageRole.UNKNOWN
    disposition = str(row.get("disposition") or "UNKNOWN")
    category = failure_category(row)
    if category == 'NON_CLAIM_PAGE':
        findings.append(Finding(
            "NON_CLAIM_PAGE" if page_role_verified else "NON_CLAIM_PAGE_CANDIDATE",
            "page_routing", None,
            (str((row.get("unstructured_reg_fallback") or {}).get("reason") or "MAILROOM_OR_FAX"),),
            ("KEEP_AS_BUNDLE_ATTACHMENT",) if page_role_verified else
            ("VERIFY_PAGE_ROLE_AND_BUNDLE", "HUMAN_REVIEW"),
            "VERIFIED_PAGE_ROLE" if page_role_verified else "TEXT_SIGNATURE_ONLY", 0))
    elif disposition == "REGISTRATION_FAILED":
        if role in NON_CLAIM_CANDIDATES:
            findings.append(Finding(
                "NON_CLAIM_PAGE" if page_role_verified else "NON_CLAIM_PAGE_CANDIDATE",
                "page_routing", None, (role.value,),
                ("KEEP_AS_BUNDLE_ATTACHMENT",) if page_role_verified else
                ("VERIFY_PAGE_ROLE_AND_BUNDLE", "HUMAN_REVIEW"),
                "VERIFIED_PAGE_ROLE" if page_role_verified else "TEXT_SIGNATURE_ONLY", 0))
        elif role == PageRole.UB04 and row.get("template_id") == "cms1500":
            findings.append(Finding("FORM_FAMILY_MISMATCH", "page_routing", None,
                (role.value, "CMS1500_TEMPLATE_SELECTED"),
                ("ROUTE_TO_QUALIFIED_UB04_TEMPLATE", "HUMAN_REVIEW")))
        elif category == 'TEMPLATE_SELECTION_FAILURE':
            findings.append(Finding('TEMPLATE_SELECTION_UNRESOLVED', 'template_selection', None,
                (str(row.get('registration_reason') or 'MISSING_SELECTION_EVIDENCE'),
                 *tuple(row.get('template_rejection_reasons') or ())),
                ('VERIFY_REFERENCE_ASSET_INTEGRITY', 'VERIFY_REQUIRED_ANCHORS', 'HUMAN_REVIEW')))
        else:
            reasons = tuple(filter(None, str(row.get("registration_reason") or "").split(",")))
            if any(r in reasons for r in ("insufficient_keypoints", "insufficient_good_matches",
                                          "insufficient_inliers", "low_inlier_ratio", "low_coverage")):
                findings.append(Finding("INSUFFICIENT_SPATIAL_SUPPORT", "registration", None,
                    reasons, ("BOUNDED_FEATURE_BUDGET_6000_12000", "RECHECK_ALL_GEOMETRY_GATES", "HUMAN_REVIEW"), max_attempts=2))
            if any(r.startswith("unsafe_") or r == "invalid_transformed_corners" for r in reasons):
                findings.append(Finding("UNSAFE_TRANSFORM", "registration", None, reasons,
                    ("VERIFY_FAMILY_AND_LANDMARKS", "QUALIFIED_ALTERNATE_REGISTRATION", "HUMAN_REVIEW")))
            if not findings:
                findings.append(Finding("REGISTRATION_UNRESOLVED", "registration", None,
                    reasons or ("MISSING_REGISTRATION_EVIDENCE",),
                    ("ACQUIRE_LOCAL_PAGE_CLASSIFICATION", "VERIFY_TEMPLATE_ASSET", "HUMAN_REVIEW")))
    elif disposition not in {"TRUE_STP", "HITL"}:
        findings.append(Finding("PIPELINE_OR_CONTRACT_FAILURE", "runtime", None,
            (disposition,), ("RESTORE_STAGE_ARTIFACT_AND_RUNTIME", "RESUME_FROM_VALID_CHECKPOINT")))
    if disposition == "HITL":
        fallback = row.get("unstructured_reg_fallback") or {}
        if row.get('registration_ok') is False:
            findings.append(Finding('TEMPLATE_SELECTION_FALLBACK_REQUIRES_REVIEW'
                if category == 'TEMPLATE_SELECTION_FAILURE' else 'REGISTRATION_FALLBACK_REQUIRES_REVIEW',
                'template_selection' if category == 'TEMPLATE_SELECTION_FAILURE' else 'registration', None,
                (str(row.get('registration_reason') or 'MISSING_REGISTRATION_EVIDENCE'),),
                ('VERIFY_TEMPLATE_AND_REGISTERED_ROI', 'QUALIFIED_ALTERNATE_REGISTRATION', 'HUMAN_REVIEW')))
        if fallback.get("acceptance_gap") == "GOVERNED_FIELD_AND_CLAIM_DECISIONS_REQUIRED":
            findings.append(Finding("UNSTRUCTURED_CANDIDATES_REQUIRE_GOVERNED_DECISION",
                "claim_decision", None, ("FIELD_PRESENCE_IS_NOT_ACCEPTANCE",),
                ("BUILD_FAMILY_SPECIFIC_FIELD_EVIDENCE", "EXISTING_CLAIM_DECISION_SERVICE", "HUMAN_REVIEW")))
        fields = row.get("fields") or {}
        for field in row.get("critical_blockers") or []:
            state = fields.get(field) or {}
            reasons = tuple(str(r) for r in state.get("reasons") or ())
            mechanisms: list[tuple[str, tuple[str, ...]]] = []
            if any("EMPTY" in r or "NO_NONEMPTY" in r for r in reasons):
                mechanisms.append(("EMPTY_OCR_NOT_PROVEN_BLANK", ("CHECK_REGISTERED_ROI", "LOCAL_ALTERNATE_CROP_AND_ENGINE", "HUMAN_REVIEW")))
            if any("INVALID_FORMAT" in r or "NORMALIZATION_FAILED" in r for r in reasons):
                mechanisms.append(("INVALID_VALUE", ("RANK_BY_EXISTING_VALIDATORS", "BOUNDED_LOCAL_FIELD_RECOVERY", "HUMAN_REVIEW")))
            if any("CONFLICT" in r for r in reasons):
                mechanisms.append(("CANDIDATE_DISAGREEMENT", ("CHECK_CROP_AND_ENGINE_PROVENANCE", "INDEPENDENT_CONFIRMATION", "HUMAN_REVIEW")))
            if any("UNCORROBORATED" in r or "INDEPENDENT_EVIDENCE_REQUIRED" in r or
                   r.startswith("MISSING_E") for r in reasons):
                steps = (("ACQUIRE_BOX28_CROP_EVIDENCE", "RECONCILE_OBSERVED_LINE_CHARGES")
                         if field == "total_charge" else ("ACQUIRE_MISSING_POLICY_EVIDENCE",))
                mechanisms.append(("MISSING_CORROBORATING_EVIDENCE", (*steps, "HUMAN_REVIEW")))
            if any("CONFIDENCE_BELOW" in r or "CALIBRATION_REQUIRED" in r for r in reasons):
                mechanisms.append(("CALIBRATION_OR_CONFIDENCE_GAP", ("VERIFY_CALIBRATION_ON_HELD_OUT_LABELS", "INDEPENDENT_CONFIRMATION", "HUMAN_REVIEW")))
            if not mechanisms:
                mechanisms.append(("UNRESOLVED_CRITICAL_FIELD", ("INSPECT_FIELD_EVIDENCE_BUNDLE", "HUMAN_REVIEW")))
            findings.extend(Finding(name, "field_decision", field, reasons, steps)
                            for name, steps in mechanisms)
    return {"version": VERSION, "failure_category": failure_category(row), "page_role": role.value,
            "page_role_verified": page_role_verified,
            "page_text_available": page_text is not None,
            "findings": [asdict(finding) for finding in findings],
            "acceptance_authority": "EXISTING_FIELD_AND_CLAIM_DECISION_GATES",
            "cloud_execution_authorized": False,
            "independent_accuracy_established": False}


def validate_resume_contract(run_dir, contract: Mapping[str, Any], *, resume: bool) -> None:
    """Prevent old/new policies or routing modes from sharing resumed metrics."""
    import json
    from pathlib import Path

    root = Path(run_dir)
    target = root / "independent_run_contract.json"
    ledger = root / "results.jsonl"
    if ledger.is_file() and ledger.stat().st_size:
        if not resume:
            raise ValueError("Existing results present; use a fresh output directory for a fresh run")
        if not target.is_file():
            raise ValueError("Existing results lack a qualified run contract; use a fresh output directory")
        previous = json.loads(target.read_text(encoding="utf-8"))
        if previous != dict(contract):
            raise ValueError("Run policy, source or classification changed; use a fresh output directory")
    root.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(contract), indent=2) + "\n", encoding="utf-8")
