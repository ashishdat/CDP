"""Field recovery router v13 — missing ink · overlap · conflict.

Classifies residual field failures and returns an ordered tool ladder.
Does not invent ink; does not call cloud itself — callers execute steps
under stop-ladder + doc latency budget gates.

Config: ``config/field_recovery_toolstack_v13.yaml``
Design: ``docs/FIELD_RECOVERY_TOOLSTACK_V13.md``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "field_recovery_toolstack_v13.yaml"


class FailureMode(StrEnum):
    MISSING_INK = "MISSING_INK"
    OVERLAP = "OVERLAP"
    CONFLICT = "CONFLICT"
    NONE = "NONE"


class RecoveryTool(StrEnum):
    DUAL_LOCAL = "dual_local"
    TESS_DIGITS = "tess_digits"
    CHARGE_WINDOWS = "charge_windows"
    CASH_RULING = "cash_ruling"
    AZURE_DI_CROP = "azure_di_crop"
    VISION_CROP = "vision_crop"
    TROCR = "trocr"
    CONFLICT_AGENT = "conflict_agent"
    HITL = "hitl"


@dataclass(frozen=True)
class RecoveryPlan:
    mode: FailureMode
    field_name: str
    gap_class: str | None
    steps: tuple[RecoveryTool, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "field_name": self.field_name,
            "gap_class": self.gap_class,
            "steps": [s.value for s in self.steps],
            "reason": self.reason,
        }


@lru_cache(maxsize=4)
def load_toolstack_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.is_file():
        return {}
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return dict(payload)


def _field_family(field_name: str) -> str:
    key = (field_name or "").casefold()
    if key in {"total_charge", "total_charges", "charges", "charge_amount"}:
        return "total_charge"
    if key in {"patient_dob", "date_of_birth"}:
        return "patient_dob"
    if key in {"insured_id_number", "member_id", "subscriber_id"}:
        return "insured_id_number"
    if key in {"patient_name", "insured_name"}:
        return "patient_name"
    return key or "unknown"


def _has_shaped_currency(candidates: Sequence[Mapping[str, Any]] | None) -> bool:
    try:
        from packages.claim_evidence.line_sum_authority import parse_currency
    except Exception:  # noqa: BLE001
        return False
    for cand in candidates or []:
        if not isinstance(cand, Mapping):
            continue
        if parse_currency(cand.get("value") or cand.get("raw_value")) is not None:
            return True
    return False


def _charge_overlap_signals(
    candidates: Sequence[Mapping[str, Any]] | None,
    observed_line_charges: Sequence[str] | None,
) -> list[str]:
    """Detect same-ink parse twins among charge candidates / line Σ."""
    try:
        from packages.claim_evidence.charge_total_authority import is_units_bleed_cents
        from packages.claim_evidence.line_sum_authority import (
            format_currency,
            is_currency_digit_drop_twin,
            is_decimal_place_shift,
            is_scale_shift,
            parse_currency,
        )
    except Exception:  # noqa: BLE001
        return []

    amounts: list[str] = []
    for cand in candidates or []:
        if not isinstance(cand, Mapping):
            continue
        amt = parse_currency(cand.get("value") or cand.get("raw_value"))
        if amt is None:
            continue
        amounts.append(format_currency(amt))
    amounts = list(dict.fromkeys(amounts))
    signals: list[str] = []
    for i, left in enumerate(amounts):
        for right in amounts[i + 1 :]:
            if is_decimal_place_shift(left, right):
                signals.append("PLACE_SHIFT")
            if is_scale_shift(left, right):
                signals.append("SCALE_SHIFT")
            if is_currency_digit_drop_twin(left, right):
                signals.append("DIGIT_DROP")
            ld = "".join(ch for ch in left if ch.isdigit())
            rd = "".join(ch for ch in right if ch.isdigit())
            if ld and rd and ld != rd and (ld in rd or rd in ld):
                signals.append("DIGIT_SUBSTRING")
        if is_units_bleed_cents(left):
            signals.append("BLEED_CENTS")
    if observed_line_charges and amounts:
        from decimal import Decimal

        line_amts = [parse_currency(x) for x in observed_line_charges]
        line_amts = [a for a in line_amts if a is not None]
        if line_amts:
            line_txt = format_currency(sum(line_amts, start=Decimal("0")))
            for left in amounts:
                if is_decimal_place_shift(left, line_txt) or is_scale_shift(
                    left, line_txt
                ):
                    signals.append("BOX28_LINE_PLACE_SHIFT")
    return list(dict.fromkeys(signals))


def classify_failure_mode(
    field_name: str,
    *,
    gap_class: str | None = None,
    reason_codes: Sequence[str] | None = None,
    candidates: Sequence[Mapping[str, Any]] | None = None,
    observed_text: str = "",
    observed_line_charges: Sequence[str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> FailureMode:
    """Classify residual failure into MISSING_INK / OVERLAP / CONFLICT / NONE."""
    cfg = dict(config or load_toolstack_config())
    reasons = {str(r) for r in (reason_codes or [])}
    gap = (gap_class or "").strip().upper()
    family = _field_family(field_name)
    text = (observed_text or "").strip()
    if not text:
        for cand in candidates or []:
            if isinstance(cand, Mapping):
                text = str(cand.get("value") or cand.get("raw_value") or "").strip()
                if text:
                    break

    reason_map = {
        str(k).upper(): FailureMode(str(v))
        for k, v in (cfg.get("reason_to_class") or {}).items()
        if str(v) in FailureMode.__members__
    }
    gap_map = {
        str(k).upper(): FailureMode(str(v))
        for k, v in (cfg.get("gap_to_class") or {}).items()
        if str(v) in FailureMode.__members__
    }

    # Explicit reason codes first (most precise).
    for code in reasons:
        mapped = reason_map.get(code.upper())
        if mapped is not None:
            return mapped
        for prefix, mode in reason_map.items():
            if code.upper().startswith(prefix) or prefix in code.upper():
                return mode

    # Charge overlap detectors before generic gap map.
    if family == "total_charge":
        signals = _charge_overlap_signals(candidates, observed_line_charges)
        if signals:
            return FailureMode.OVERLAP
        line_n = len(
            [x for x in (observed_line_charges or []) if str(x).strip()]
        )
        if not text and line_n == 0:
            return FailureMode.MISSING_INK
        if text and line_n == 0 and "MISSING_E4_DETERMINISTIC_VALIDATION" in {
            r.upper() for r in reasons
        }:
            return FailureMode.OVERLAP
        if not _has_shaped_currency(candidates) and line_n == 0:
            return FailureMode.MISSING_INK

    if gap and gap in gap_map:
        mode = gap_map[gap]
        # Refine EVIDENCE_POLICY_GAP by field.
        if gap == "EVIDENCE_POLICY_GAP":
            if "MISSING_E2" in " ".join(reasons).upper():
                return FailureMode.CONFLICT
            if "MISSING_E4" in " ".join(reasons).upper():
                return FailureMode.OVERLAP
        return mode

    if family in {"patient_name", "insured_name"}:
        if "CONFLICT_MARGIN_TOO_SMALL" in reasons or gap == "NAME_ENGINE_CONFLICT":
            return FailureMode.CONFLICT
        if not text:
            return FailureMode.MISSING_INK

    if family == "insured_id_number":
        if any("SHORT_PADDED" in r.upper() or "UNSHAPED" in r.upper() for r in reasons):
            return FailureMode.MISSING_INK
        if "CONFLICT_MARGIN_TOO_SMALL" in reasons:
            return FailureMode.CONFLICT

    if family == "patient_dob":
        if not text:
            return FailureMode.MISSING_INK
        if "CONFLICT_MARGIN_TOO_SMALL" in reasons:
            return FailureMode.CONFLICT

    if gap:
        return gap_map.get(gap, FailureMode.MISSING_INK)

    return FailureMode.NONE


def plan_recovery(
    field_name: str,
    *,
    gap_class: str | None = None,
    reason_codes: Sequence[str] | None = None,
    candidates: Sequence[Mapping[str, Any]] | None = None,
    observed_text: str = "",
    observed_line_charges: Sequence[str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> RecoveryPlan:
    """Return ordered recovery tools for this field residual."""
    cfg = dict(config or load_toolstack_config())
    mode = classify_failure_mode(
        field_name,
        gap_class=gap_class,
        reason_codes=reason_codes,
        candidates=candidates,
        observed_text=observed_text,
        observed_line_charges=observed_line_charges,
        config=cfg,
    )
    family = _field_family(field_name)
    if mode is FailureMode.NONE:
        return RecoveryPlan(
            mode=mode,
            field_name=field_name,
            gap_class=gap_class,
            steps=(),
            reason="no_residual",
        )

    ladders = (cfg.get("ladders") or {}).get(mode.value) or {}
    raw_steps = ladders.get(family) or ladders.get("total_charge") or ["hitl"]
    steps: list[RecoveryTool] = []
    for name in raw_steps:
        try:
            steps.append(RecoveryTool(str(name)))
        except ValueError:
            continue
    if not steps or steps[-1] is not RecoveryTool.HITL:
        steps.append(RecoveryTool.HITL)

    reason_bits = []
    if gap_class:
        reason_bits.append(f"gap={gap_class}")
    if reason_codes:
        reason_bits.append(f"reasons={list(reason_codes)[:4]}")
    if family == "total_charge":
        sigs = _charge_overlap_signals(candidates, observed_line_charges)
        if sigs:
            reason_bits.append(f"overlap={sigs}")

    return RecoveryPlan(
        mode=mode,
        field_name=field_name,
        gap_class=gap_class,
        steps=tuple(steps),
        reason="; ".join(reason_bits) or mode.value,
    )


def cloud_tools_for_plan(plan: RecoveryPlan) -> tuple[RecoveryTool, ...]:
    """Cloud-costing steps (DI / vision / TrOCR) in plan order — max one shaped."""
    cloud = {
        RecoveryTool.AZURE_DI_CROP,
        RecoveryTool.VISION_CROP,
        RecoveryTool.TROCR,
    }
    return tuple(s for s in plan.steps if s in cloud)
