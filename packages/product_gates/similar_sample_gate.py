"""Similar-sample product gate — 97% claim-page STP · FA=0 accepted accuracy."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from packages.extraction_recovery.residual_taxonomy import classify_row

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "product_stp_accuracy_contract_v1.yaml"


@lru_cache(maxsize=4)
def load_product_contract(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONTRACT
    if not cfg_path.is_file():
        return {}
    return dict(yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {})


@dataclass(frozen=True)
class ProductGateResult:
    pass_gate: bool
    claim_page_stp: float
    claim_pages: int
    true_stp: int
    hitl: int
    registration_failed: int
    false_accepts: int | None
    accepted_field_precision: float | None
    fa_status: str
    residual_counts: dict[str, int]
    reasons: tuple[str, ...]
    targets: dict[str, Any]
    fa_report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.pass_gate,
            "claim_page_stp": self.claim_page_stp,
            "claim_pages": self.claim_pages,
            "true_stp": self.true_stp,
            "hitl": self.hitl,
            "registration_failed": self.registration_failed,
            "false_accepts": self.false_accepts,
            "accepted_field_precision": self.accepted_field_precision,
            "fa_status": self.fa_status,
            "residual_counts": dict(self.residual_counts),
            "reasons": list(self.reasons),
            "targets": dict(self.targets),
            "fa_report": dict(self.fa_report),
        }


def evaluate_similar_sample_gate(
    merged_rows: Mapping[str, Mapping[str, Any]],
    *,
    contract: Mapping[str, Any] | None = None,
    allow_incomplete_gt: bool = False,
    run_manifest: Mapping[str, Any] | None = None,
    allow_tip_seed: bool = False,
    allow_missing_manifest: bool = False,
    allow_fast: bool = False,
) -> ProductGateResult:
    cfg = dict(contract or load_product_contract())
    targets = dict(cfg.get("targets") or {})
    stp_min = float(targets.get("claim_page_stp_min") or 0.97)
    precision_min = float(targets.get("accepted_field_precision_min") or 1.0)
    max_fa = int(targets.get("max_false_accepts") or 0)
    gates = dict(cfg.get("gates") or {})

    profile_ok = True
    profile_reason = "PROFILE_NOT_REQUIRED"
    if bool(gates.get("require_product_profile", True)):
        from packages.run_profiles.profiles import gate_allows_profile

        profile_ok, profile_reason = gate_allows_profile(
            run_manifest,
            allow_tip_seed=allow_tip_seed,
            allow_missing_manifest=allow_missing_manifest,
            allow_fast=allow_fast,
        )

    disp = Counter(r.get("disposition") for r in merged_rows.values())
    claim_pages = sum(
        1
        for r in merged_rows.values()
        if r.get("disposition") != "REGISTRATION_FAILED"
    )
    true_stp = int(disp.get("TRUE_STP", 0))
    hitl = int(disp.get("HITL", 0))
    reg = int(disp.get("REGISTRATION_FAILED", 0))
    rate = (true_stp / claim_pages) if claim_pages else 0.0

    residual_counts: Counter[str] = Counter()
    for row in merged_rows.values():
        if row.get("disposition") != "HITL":
            continue
        residual_counts[classify_row(row).value] += 1

    fa_report: dict[str, Any] = {"status": "SKIPPED"}
    gt_path = ROOT / str(gates.get("score_gt") or "")
    gold_only = bool(gates.get("gold_only", True))
    apply_quarantine = bool(gates.get("apply_quarantine", True))
    try:
        from packages.evaluation.agent_gt_score import score_merged_against_agent_gt

        fa_report = score_merged_against_agent_gt(
            merged_rows,
            gt_path,
            gold_only=gold_only,
            apply_quarantine=apply_quarantine,
        )
    except Exception as exc:  # noqa: BLE001
        fa_report = {"status": "ERROR", "error": f"{type(exc).__name__}:{exc}"}

    fa_status = str(fa_report.get("status") or "UNKNOWN")
    false_accepts = fa_report.get("false_accepts")
    precision = fa_report.get("accepted_field_precision")

    reasons: list[str] = []
    if not profile_ok:
        reasons.append(f"RUN_PROFILE_GATE:{profile_reason}")
    else:
        reasons.append(f"RUN_PROFILE_OK:{profile_reason}")

    stp_ok = rate + 1e-6 >= stp_min
    if not stp_ok:
        reasons.append(f"CLAIM_PAGE_STP_BELOW_TARGET:{rate:.4f}<{stp_min}")

    fa_ok = True
    if fa_status == "SCORED":
        fa_ok = int(false_accepts or 0) <= max_fa and (
            precision is None or float(precision) + 1e-9 >= precision_min
        )
        if not fa_ok:
            reasons.append(
                f"FALSE_ACCEPT_GATE:fa={false_accepts},precision={precision}"
            )
    elif fa_status == "GT_MISSING":
        if gates.get("require_gt_for_green_fa", True) and not allow_incomplete_gt:
            fa_ok = False
            reasons.append("GT_MISSING_FA_INCOMPLETE")
        else:
            reasons.append("GT_MISSING_ALLOWED")
    elif fa_status == "ERROR":
        fa_ok = False
        reasons.append(f"FA_SCORE_ERROR:{fa_report.get('error')}")

    # Residual honesty: recoverable pool must be published; empty is OK.
    if not residual_counts and hitl:
        reasons.append("RESIDUAL_TAXONOMY_EMPTY_WITH_HITL")

    pass_gate = bool(profile_ok and stp_ok and fa_ok)
    if pass_gate:
        reasons.append("PRODUCT_GATE_PASS")

    return ProductGateResult(
        pass_gate=pass_gate,
        claim_page_stp=round(rate, 4),
        claim_pages=claim_pages,
        true_stp=true_stp,
        hitl=hitl,
        registration_failed=reg,
        false_accepts=int(false_accepts) if false_accepts is not None else None,
        accepted_field_precision=float(precision) if precision is not None else None,
        fa_status=fa_status,
        residual_counts=dict(residual_counts),
        reasons=tuple(reasons),
        targets={
            "claim_page_stp_min": stp_min,
            "accepted_field_precision_min": precision_min,
            "max_false_accepts": max_fa,
            "gold_only": gold_only,
            "apply_quarantine": apply_quarantine,
            "require_product_profile": bool(gates.get("require_product_profile", True)),
            "run_profile": (run_manifest or {}).get("profile") if run_manifest else None,
        },
        fa_report={
            k: fa_report[k]
            for k in (
                "status",
                "claims_scored",
                "accepted_fields_scored",
                "false_accepts",
                "exact_matches",
                "accepted_field_precision",
                "gold_only",
                "quarantine_applied",
                "quarantined_fields",
                "false_accept_examples",
                "error",
            )
            if k in fa_report
        },
    )
