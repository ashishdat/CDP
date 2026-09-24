"""Independent case router — page-class → recovery path.

Consolidates Independent-1000 failure modes that previously forked ad-hoc
across cascade REG, unstructured DI, and field-ink residuals:

  MAILROOM / FAX     → REG (no claim ink; never invent HITL names)
  CMS1500            → geometry cascade + field residual toolstack
  UB04 / FREEFORM    → unstructured DI heuristics (precision-safe STP)
  UNKNOWN            → try CMS geometry; on miss fall through unstructured

This module classifies and returns a ``CaseRoute``. Callers execute the path.
Field-level residual ladders stay in ``field_recovery_router`` (downstream).

Config: ``config/independent_case_toolstack_v1.yaml``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from packages.document_finance.families import (
    DocumentFamily,
    FamilyClassification,
    classify_document_family,
)
from packages.extraction_recovery.unstructured_reg_fallback import (
    _is_mailroom_only_page,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "independent_case_toolstack_v1.yaml"

_CRITICAL = frozenset(
    {"patient_name", "patient_dob", "insured_id_number", "total_charge"}
)


class CasePath(StrEnum):
    MAILROOM_REG = "MAILROOM_REG"
    CMS_GEOMETRY = "CMS_GEOMETRY"
    UNSTRUCTURED_DI = "UNSTRUCTURED_DI"
    FIELD_INK_RESIDUAL = "FIELD_INK_RESIDUAL"


class CaseDispositionPolicy(StrEnum):
    """How shaped fields promote to ops ledger dispositions."""

    KEEP_REG = "KEEP_REG"
    UNSTRUCTURED_PROMOTE = "UNSTRUCTURED_PROMOTE"  # 4 critical → STP else HITL
    CMS_CLAIM_DECISION = "CMS_CLAIM_DECISION"  # claim_decision STP/HITL


@dataclass(frozen=True)
class CaseRoute:
    path: CasePath
    family: DocumentFamily
    family_confidence: float
    disposition_policy: CaseDispositionPolicy
    hitl_track: str | None
    reason: str
    evidence: tuple[str, ...] = ()
    finish_document_family: str = "CMS1500"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path.value,
            "family": self.family.value,
            "family_confidence": self.family_confidence,
            "disposition_policy": self.disposition_policy.value,
            "hitl_track": self.hitl_track,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "finish_document_family": self.finish_document_family,
        }


@lru_cache(maxsize=4)
def load_independent_case_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.is_file():
        return {}
    return dict(yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {})


def _fax_boilerplate(text: str) -> bool:
    import re

    if re.search(
        r"fax\s*image|therefore\s+better|original\s+source\s+may\s+be\s+bad",
        text or "",
        re.IGNORECASE,
    ):
        # Real claim ink still wins.
        if re.search(
            r"CMS-?\s*1500|UB-?\s*04|BIRTHDATE|PATIENT\s*NAME|TOTAL\s*CHARGE|NUCC",
            text or "",
            re.IGNORECASE,
        ):
            return False
        return True
    return False


def classify_independent_case(
    di_text: str | None,
    *,
    registration_ok: bool = False,
    field_ink_hitl: bool = False,
    barcode_text: str | None = None,
    layout_hints: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> CaseRoute:
    """Classify an Independent page into a recovery path.

    Prefer calling with DI/full-page text. When ``registration_ok`` and the
    claim is already field-ink HITL, route to residual toolstack instead of
    re-running unstructured DI.
    """
    cfg = dict(config or load_independent_case_config())
    text = di_text or ""

    if field_ink_hitl and registration_ok:
        return CaseRoute(
            path=CasePath.FIELD_INK_RESIDUAL,
            family=DocumentFamily.CMS1500,
            family_confidence=0.85,
            disposition_policy=CaseDispositionPolicy.CMS_CLAIM_DECISION,
            hitl_track="FIELD_INK",
            reason="REGISTERED_CMS_FIELD_INK_HITL",
            evidence=("registration_ok", "field_ink_hitl"),
            finish_document_family="CMS1500",
        )

    if _is_mailroom_only_page(text) or _fax_boilerplate(text):
        fam = classify_document_family(text, barcode_text=barcode_text)
        return CaseRoute(
            path=CasePath.MAILROOM_REG,
            family=DocumentFamily.SEPARATOR
            if fam.family is DocumentFamily.UNKNOWN
            else fam.family,
            family_confidence=max(0.9, fam.confidence),
            disposition_policy=CaseDispositionPolicy.KEEP_REG,
            hitl_track=None,
            reason="MAILROOM_OR_FAX_NO_CLAIM_INK",
            evidence=tuple(fam.evidence) + ("mailroom_or_fax",),
            finish_document_family="CMS1500",
        )

    fam: FamilyClassification = classify_document_family(
        text, barcode_text=barcode_text, layout_hints=dict(layout_hints or {})
    )

    # Explicit family → path map from YAML (with safe defaults).
    family_paths = dict(cfg.get("family_paths") or {})
    default_map = {
        DocumentFamily.CMS1500.value: CasePath.CMS_GEOMETRY.value,
        DocumentFamily.UB04.value: CasePath.UNSTRUCTURED_DI.value,
        DocumentFamily.REIMBURSEMENT_SUPERBILL.value: CasePath.UNSTRUCTURED_DI.value,
        DocumentFamily.RUNNING_ACCOUNT_STATEMENT.value: CasePath.UNSTRUCTURED_DI.value,
        DocumentFamily.EOB.value: CasePath.MAILROOM_REG.value,
        DocumentFamily.SEPARATOR.value: CasePath.MAILROOM_REG.value,
        DocumentFamily.ATTACHMENT.value: CasePath.MAILROOM_REG.value,
        DocumentFamily.UNKNOWN.value: CasePath.CMS_GEOMETRY.value,
    }
    path_name = str(
        family_paths.get(fam.family.value) or default_map.get(fam.family.value) or "CMS_GEOMETRY"
    )
    try:
        path = CasePath(path_name)
    except ValueError:
        path = CasePath.CMS_GEOMETRY

    if registration_ok and path is CasePath.CMS_GEOMETRY:
        return CaseRoute(
            path=CasePath.CMS_GEOMETRY,
            family=fam.family,
            family_confidence=fam.confidence,
            disposition_policy=CaseDispositionPolicy.CMS_CLAIM_DECISION,
            hitl_track=None,
            reason="CMS_GEOMETRY_REGISTERED",
            evidence=tuple(fam.evidence),
            finish_document_family="CMS1500",
        )

    if path is CasePath.MAILROOM_REG:
        return CaseRoute(
            path=CasePath.MAILROOM_REG,
            family=fam.family,
            family_confidence=fam.confidence,
            disposition_policy=CaseDispositionPolicy.KEEP_REG,
            hitl_track=None,
            reason=f"FAMILY_{fam.family.value}_NO_CLAIM_PATH",
            evidence=tuple(fam.evidence),
            finish_document_family="CMS1500",
        )

    if path is CasePath.UNSTRUCTURED_DI:
        finish = "UB04" if fam.family is DocumentFamily.UB04 else "CMS1500"
        return CaseRoute(
            path=CasePath.UNSTRUCTURED_DI,
            family=fam.family,
            family_confidence=fam.confidence,
            disposition_policy=CaseDispositionPolicy.UNSTRUCTURED_PROMOTE,
            hitl_track="UNSTRUCTURED_DI",
            reason=f"FAMILY_{fam.family.value}_UNSTRUCTURED_DI",
            evidence=tuple(fam.evidence),
            finish_document_family=finish,
        )

    # UNKNOWN / CMS without registration yet: prefer geometry; caller falls
    # through to unstructured on miss.
    return CaseRoute(
        path=CasePath.CMS_GEOMETRY,
        family=fam.family,
        family_confidence=fam.confidence,
        disposition_policy=CaseDispositionPolicy.CMS_CLAIM_DECISION,
        hitl_track=None,
        reason="TRY_CMS_GEOMETRY_THEN_UNSTRUCTURED",
        evidence=tuple(fam.evidence) + ("geometry_first",),
        finish_document_family="CMS1500",
    )


def promote_unstructured_fields(fields: Mapping[str, str] | None) -> tuple[str, list[str]]:
    """Return (disposition, critical_blockers) for unstructured DI fields."""
    shaped = {k: v for k, v in dict(fields or {}).items() if str(v or "").strip()}
    missing = sorted(_CRITICAL - set(shaped))
    if not shaped:
        return "REGISTRATION_FAILED", missing
    if not missing:
        return "TRUE_STP", []
    return "HITL", missing
