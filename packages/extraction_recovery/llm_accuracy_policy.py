"""Accuracy-first LLM / cloud residual policy.

Latency stop-ladder and doc budgets may skip cloud when locals are safely
settled. For critical STP gaps (0-line Box28, place-shift, short-padded ID,
name conflict) we **must** still call DI and/or vision LLM — otherwise
dual-local ink dies as MISSING_E4 / SHORT_PADDED / CONFLICT_MARGIN.

Never invent amounts or IDs; LLM may only corroborate or arbitrate listed rivals.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

# Strong E4 facts that unlock C3 total_charge without inventing ink.
CHARGE_CLOUD_LOCAL_FACTS = frozenset(
    {
        "CHARGE_DI_LOCAL_CONFIRMED",
        "CHARGE_VISION_LOCAL_CONFIRMED",
    }
)


def _env_on(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def accuracy_first_llm_enabled() -> bool:
    """Master switch — default on. Set CDP_ACCURACY_FIRST_LLM=0 to revert."""
    return _env_on("CDP_ACCURACY_FIRST_LLM", "1")


def azure_di_charge_default_on() -> bool:
    """Library default for DI charge residual (accuracy path)."""
    return _env_on("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")


def _line_charges(row: Mapping[str, Any] | None) -> list[str]:
    if not row:
        return []
    meta = row.get("observed_line_charges")
    if isinstance(meta, list):
        return [str(x) for x in meta if str(x).strip()]
    return []


def _cascade_value(row: Mapping[str, Any]) -> str:
    cascade = row.get("cascade") or {}
    return str(cascade.get("value") or "").strip()


def charge_accuracy_needs_di(
    row: Mapping[str, Any],
    *,
    observed_line_charges: Sequence[str] | None = None,
) -> bool:
    """True when DI charge crop is required for strong E4 / overlap resolve."""
    if not accuracy_first_llm_enabled():
        return False
    lines = (
        [str(x) for x in observed_line_charges if str(x).strip()]
        if observed_line_charges is not None
        else _line_charges(row)
    )
    cands = list(row.get("candidates") or [])
    # 0 lines + any local currency → need DI partner for E4.
    if len(lines) == 0 and cands:
        return True
    # Place-shift / scale vs line Σ.
    if lines:
        try:
            from packages.claim_evidence.line_sum_authority import (
                format_currency,
                is_decimal_place_shift,
                is_scale_shift,
                parse_currency,
            )
            from decimal import Decimal

            line_amts = [parse_currency(x) for x in lines]
            line_amts = [a for a in line_amts if a is not None]
            if line_amts:
                line_txt = format_currency(sum(line_amts, start=Decimal("0")))
                for cand in cands:
                    eng = str(cand.get("engine") or "").casefold()
                    if any(
                        t in eng
                        for t in ("gpt4o", "claude", "anthropic", "document_intelligence")
                    ):
                        continue
                    amt = parse_currency(cand.get("value") or cand.get("raw_value"))
                    if amt is None:
                        continue
                    txt = format_currency(amt)
                    if is_decimal_place_shift(txt, line_txt) or is_scale_shift(
                        txt, line_txt
                    ):
                        return True
        except Exception:  # noqa: BLE001
            return True
    return False


def charge_accuracy_needs_vision(
    row: Mapping[str, Any],
    *,
    di_ready: bool = False,
    di_agrees_local: bool = False,
    observed_line_charges: Sequence[str] | None = None,
) -> bool:
    """True when Claude/gpt-4o crop must still run after (optional) DI.

    Skip only when DI already agreed with locals (E4 path complete) **and**
    there is no place-shift vs lines. Otherwise LLM corroborates or arbitrates.
    """
    if not accuracy_first_llm_enabled():
        # Legacy: skip second cloud when DI already agrees.
        return not (di_ready and di_agrees_local)
    if charge_accuracy_needs_di(row, observed_line_charges=observed_line_charges):
        lines = (
            [str(x) for x in observed_line_charges if str(x).strip()]
            if observed_line_charges is not None
            else _line_charges(row)
        )
        # 0-line: DI agree is enough for E4 — LLM optional.
        if len(lines) == 0 and di_ready and di_agrees_local:
            return False
        # Place-shift vs lines: always need vision arbitrator even if DI agrees.
        if len(lines) > 0:
            return True
        # 0-line but DI abstained / disagreed → LLM required for vision+local E4.
        return not (di_ready and di_agrees_local)
    # Generic unsettled charge: prefer LLM unless DI already settled agreement.
    return not (di_ready and di_agrees_local)


def id_accuracy_needs_vision(row: Mapping[str, Any]) -> bool:
    if not accuracy_first_llm_enabled():
        return True
    from packages.extraction_recovery.gpt4o_crop_residual import id_needs_gpt4o

    cascade = row.get("cascade") or {}
    value = str(cascade.get("value") or "").strip()
    return id_needs_gpt4o(
        value or None,
        accepted=bool(cascade.get("accepted")),
        candidates=list(row.get("candidates") or []),
    )


def name_accuracy_needs_vision(row: Mapping[str, Any]) -> bool:
    if not accuracy_first_llm_enabled():
        return True
    from packages.extraction_recovery.gpt4o_crop_residual import name_needs_gpt4o

    cascade = row.get("cascade") or {}
    return name_needs_gpt4o(
        local_accepted=bool(cascade.get("accepted")),
        candidates=list(row.get("candidates") or []),
        gap_class=str(row.get("gap_class") or "") or None,
    )


def name_force_despite_budget(row: Mapping[str, Any]) -> bool:
    """When soft/hard budget may be overridden for name cloud residuals.

    - ``patient_name``: always force when vision is needed (Box 2 is STP-critical;
      budget-skip here caused false patient_name HITL on garbled mono-OCR).
    - ``insured_name``: override only for genuine conflict / named unread gap.
      Mono-engine E2 on Box 4 stays soft-optional (latency).
    """
    if not accuracy_first_llm_enabled():
        return False
    field = str(row.get("field") or "").casefold()
    if field == "patient_name":
        return name_accuracy_needs_vision(row)

    from packages.extraction_recovery.gpt4o_crop_residual import (
        _NAME_GAPS,
        _local_names_need_vision_tiebreak,
        name_local_engine_conflict,
    )

    cands = list(row.get("candidates") or [])
    try:
        from packages.extraction_recovery.cloud_stop_ladder import (
            cloud_stop_ladder_enabled,
            name_locals_settled,
        )

        if cloud_stop_ladder_enabled() and name_locals_settled(cands):
            return False
    except Exception:  # noqa: BLE001
        pass
    if name_local_engine_conflict(cands) or _local_names_need_vision_tiebreak(cands):
        return True
    cascade = row.get("cascade") or {}
    accepted = bool(cascade.get("accepted"))
    gap = str(row.get("gap_class") or "").upper().strip()
    # _NAME_GAPS includes "" for residual routing; empty is not a force reason.
    if gap and gap in _NAME_GAPS and not accepted:
        return True
    return False


def name_budget_unsettled(row: Mapping[str, Any]) -> bool:
    """Soft budget may skip insured mono-engine vision; patient_name stays unsettled."""
    field = str(row.get("field") or "").casefold()
    if field == "patient_name":
        return name_accuracy_needs_vision(row)
    return name_force_despite_budget(row)


def force_cloud_despite_budget(field_name: str, row: Mapping[str, Any]) -> bool:
    """Unsettled accuracy-critical residuals ignore soft/hard budget skips."""
    if not accuracy_first_llm_enabled():
        return False
    key = (field_name or "").casefold()
    if key in {"total_charge", "total_charges", "charges", "charge_amount"}:
        return charge_accuracy_needs_di(row) or charge_accuracy_needs_vision(row)
    if key in {"insured_id_number", "member_id", "subscriber_id"}:
        return id_accuracy_needs_vision(row)
    if key == "patient_name":
        # Stamp field on row so name_force sees patient_name (OCR rows carry it).
        stamped = dict(row)
        stamped.setdefault("field", field_name)
        return name_force_despite_budget(stamped)
    if key == "insured_name":
        stamped = dict(row)
        stamped.setdefault("field", field_name)
        return name_force_despite_budget(stamped)
    return False
