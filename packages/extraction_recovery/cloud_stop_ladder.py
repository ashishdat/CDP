"""Strict cloud stop ladder for field residuals.

Stop early so cascade does not casually re-contest settled ink:

1. ≥2 local families agree on shaped non-bleed / calendar / ID / name → **done**
   (no DI, no Claude/gpt-4o).
2. Local weak / blank / genuine digit or name twins → **one** cloud crop
   (DI *or* Claude/gpt-4o, never both once either shaped-succeeds).
3. Claim decision must not re-litigate fields already AUTO with authority
   (handled in ``claim_decision.service``).

Env kill-switch: ``CDP_CLOUD_STOP_LADDER=0`` restores prior always-escalate behavior.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


def cloud_stop_ladder_enabled() -> bool:
    raw = (os.environ.get("CDP_CLOUD_STOP_LADDER") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _eng(cand: Mapping[str, Any]) -> str:
    return str(cand.get("engine") or "").casefold()


def _is_cloud_engine(engine: str) -> bool:
    eng = engine.casefold()
    return any(
        t in eng
        for t in (
            "gpt4o",
            "gpt-4o",
            "claude",
            "anthropic",
            "document_intelligence",
            "azure_di",
            "azure_read",
            "trocr",
        )
    )


def _local_candidates(
    candidates: list[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for cand in candidates or []:
        if not isinstance(cand, Mapping):
            continue
        if _is_cloud_engine(_eng(cand)):
            continue
        out.append(cand)
    return out


def field_has_shaped_di(row: Mapping[str, Any]) -> bool:
    residual = row.get("azure_di_residual") or {}
    if residual.get("value") and (
        residual.get("currency_shaped")
        or residual.get("date_shaped")
        or residual.get("shaped")
    ) and not residual.get("review_only"):
        return True
    return False


def field_has_shaped_vision(row: Mapping[str, Any]) -> bool:
    residual = row.get("gpt4o_crop_residual") or {}
    if residual.get("value") and residual.get("shaped") and not residual.get(
        "review_only"
    ):
        return True
    return False


def one_cloud_already_shaped(row: Mapping[str, Any]) -> bool:
    """True when DI or Claude/gpt-4o already produced a shaped residual."""
    return field_has_shaped_di(row) or field_has_shaped_vision(row)


def charge_locals_settled(
    candidates: list[Mapping[str, Any]] | None,
    *,
    observed_line_charges: list[str] | None = None,
) -> bool:
    """≥2 local families agree on one non-bleed currency → skip cloud.

    Do **not** settle when:
    - zero observed line charges (need DI for strong E4 / Box28 corroboration)
    - settled Box28 is place/scale-shift of observed line Σ (need cloud to
      resolve digit-drop / decimal twins for SINGLE_LINE gates)
    """
    try:
        from packages.claim_evidence.charge_total_authority import is_units_bleed_cents
        from packages.claim_evidence.line_sum_authority import (
            format_currency,
            is_decimal_place_shift,
            is_scale_shift,
            parse_currency,
        )
        from packages.ocr.independence import independence_group
    except Exception:  # noqa: BLE001
        return False

    line_amts: list[Any] = []
    for raw in observed_line_charges or []:
        amt = parse_currency(raw)
        if amt is not None:
            line_amts.append(amt)
    # No line ink → dual-local Box28 alone cannot mint strong E4; keep one cloud.
    if observed_line_charges is not None and len(line_amts) == 0:
        return False

    by_amt: dict[str, set[str]] = {}
    for cand in _local_candidates(candidates):
        raw = cand.get("value") or cand.get("raw_value")
        amt = parse_currency(raw)
        if amt is None:
            continue
        txt = format_currency(amt)
        if is_units_bleed_cents(txt):
            continue
        by_amt.setdefault(txt, set()).add(independence_group(_eng(cand)))
    settled_amts = [txt for txt, groups in by_amt.items() if len(groups) >= 2]
    if not settled_amts:
        return False
    if line_amts:
        from decimal import Decimal

        line_sum = sum(line_amts, start=Decimal("0"))
        line_txt = format_currency(line_sum)
        for txt in settled_amts:
            if is_decimal_place_shift(txt, line_txt) or is_scale_shift(txt, line_txt):
                return False
            # Exact match or within $1 is fine — settled.
    return True


def dob_locals_settled(candidates: list[Mapping[str, Any]] | None) -> bool:
    """Any display-shaped calendar DOB, or ≥2 locals on same YMD → skip cloud."""
    try:
        from packages.candidate_reconciliation.reconciler import (
            _dob_is_display_shaped,
            _dob_ymd,
        )
        from packages.ocr.independence import independence_group
    except Exception:  # noqa: BLE001
        return False

    by_ymd: dict[tuple[str, str, str], set[str]] = {}
    any_shaped = False
    for cand in _local_candidates(candidates):
        text = str(cand.get("value") or "").strip()
        if not text:
            continue
        if _dob_is_display_shaped(text):
            any_shaped = True
            ymd = _dob_ymd(text)
            if ymd is not None:
                by_ymd.setdefault(ymd, set()).add(independence_group(_eng(cand)))
    if any(len(groups) >= 2 for groups in by_ymd.values()):
        return True
    # Single display-shaped local is enough to skip TrOCR→DI→Claude; policy
    # conflict on that date is not fixed by another model.
    return any_shaped


def id_locals_settled(candidates: list[Mapping[str, Any]] | None) -> bool:
    from packages.extraction_recovery.gpt4o_crop_residual import (
        id_local_already_settled,
        id_local_digit_conflict,
    )

    if not id_local_already_settled(candidates):
        return False
    return not id_local_digit_conflict(candidates)


def name_locals_settled(candidates: list[Mapping[str, Any]] | None) -> bool:
    """≥2 local families agree (soft-equivalent) on a shaped name → skip cloud.

    Soft-equivalent cliques still settle for latency; garbage / non-shaped
    tokens never enter the clique. Conflict-margin / MISSING_E2 residuals are
    handled by forcing vision when cascade did not accept + gap signals.
    """
    try:
        from packages.candidate_reconciliation.reconciler import (
            values_conflict_equivalent,
        )
        from packages.extraction_recovery.field_cascade import semantic_accept
        from packages.ocr.independence import independence_group
    except Exception:  # noqa: BLE001
        return False

    shaped: list[tuple[str, str]] = []
    for cand in _local_candidates(candidates):
        text = str(cand.get("value") or cand.get("text") or "").strip()
        if not text or not semantic_accept("patient_name", text)[0]:
            continue
        shaped.append((text, independence_group(_eng(cand))))
    if len(shaped) < 2:
        return False
    for i, (left, left_fam) in enumerate(shaped):
        families = {left_fam}
        for right, right_fam in shaped[i + 1 :]:
            if values_conflict_equivalent("patient_name", left, right):
                families.add(right_fam)
        if len(families) >= 2:
            return True
    return False


def should_skip_all_cloud(
    field_name: str,
    row: Mapping[str, Any],
    *,
    observed_line_charges: list[str] | None = None,
) -> bool:
    """Ladder step 1: locals already settled → do not call DI or Claude."""
    if not cloud_stop_ladder_enabled():
        return False
    key = (field_name or "").casefold()
    cands = list(row.get("candidates") or [])
    cascade = row.get("cascade") or {}
    if cascade.get("accepted") and key in {"patient_dob", "date_of_birth"}:
        # Cascade-accepted calendar DOB is done — residual cannot help policy fights.
        return True
    if key in {"total_charge", "total_charges", "charges", "charge_amount"}:
        # Prefer explicit lines; fall back to row metadata when wired.
        lines = observed_line_charges
        if lines is None:
            meta = row.get("observed_line_charges")
            if isinstance(meta, list):
                lines = [str(x) for x in meta if x]
        return charge_locals_settled(cands, observed_line_charges=lines)
    if key in {"patient_dob", "date_of_birth"}:
        return dob_locals_settled(cands)
    if key in {"insured_id_number", "member_id", "subscriber_id"}:
        # Cascade accept alone is not enough — weak/chrome IDs still need vision.
        return id_locals_settled(cands)
    if key in {"patient_name", "insured_name"}:
        return name_locals_settled(cands)
    return False


def should_skip_second_cloud(row: Mapping[str, Any]) -> bool:
    """Ladder step 2: one shaped cloud residual is enough — do not stack DI+Claude."""
    if not cloud_stop_ladder_enabled():
        return False
    return one_cloud_already_shaped(row)


# Authority reason codes that mean field FVA already locked the value — claim
# must not re-open that field via stale contradiction soup.
FIELD_AUTHORITY_CODES = frozenset(
    {
        "CLAIM_TOTAL_CONFIRMED",
        "CHARGE_TOTAL_AUTHORITY",
        "CASH_RULING_PRINTED_CENTS",
        "CHARGE_DI_LOCAL_CONFIRMED",
        "BOX28_OVER_BLEED_LINE_SUM",
        "LINE_TOTALS_RECONCILED",
        "LINE_TOTALS_CORROBORATED",
        "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
        "DATE_UNIQUE_CALENDAR_CORROBORATED",
        "DATE_CORROBORATED_THRESHOLD_RELIEF",
        "UNIQUE_SHAPED_ID_CORROBORATED",
        "MULTI_ENGINE_ID_CORROBORATED_THRESHOLD_RELIEF",
        "MULTI_ENGINE_AGREEMENT",
        "BOX2_INDEPENDENT_NAME_AUTHORITY",
        "NAME_STRONG_PERSON_THRESHOLD_RELIEF",
        "GPT4O_ID_DIGIT_CONFLICT_TIEBREAK",
        "GPT4O_ID_WEAK_LOCAL_RELIEVED",
        "GPT4O_NAME_INK_CONFLICT_RELIEVED",
    }
)


def field_has_authority(reason_codes: list[str] | None) -> bool:
    codes = set(reason_codes or [])
    return bool(codes & FIELD_AUTHORITY_CODES)
