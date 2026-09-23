"""Precision-safe charge total selection (no new OCR, no threshold fitting).

Closes recurring false-accept classes:
  C1 — units-bleed cents (.07/.10/.22/.32/.43) when a .00 sibling exists
  C2 — dollars-ruling trailing digit (70.00 → 701.00) when a full-window stem exists
  C3 — place-shift / digit-soup totals (already rejected upstream)

Never invents amounts. Prefer fail-closed (keep primary) over unsafe collapse
like ``251.00 → 25.00``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from packages.claim_evidence.line_sum_authority import (
    format_currency,
    is_decimal_place_shift,
    is_implausible_charge_total,
    parse_currency,
)

# Cents that almost always come from Box 24G units / dashed-ruling bleed into
# the cents column on typed CMS-1500 charges (whole-dollar claims dominate).
# Includes echo pairs (.24/.44) seen on DJKH geometry crops.
_BLEED_CENTS = frozenset({"01", "07", "10", "16", "22", "24", "32", "40", "43", "44"})
_FULL_TAGS = frozenset({"full", "line_full", "geometry", "line_geometry", "primary"})
_RULING_TAGS = frozenset({"ruling", "line_ruling"})


def _digits(text: object) -> str:
    return re.sub(r"\D", "", str(text or ""))


def _dollars_part(amount: object) -> str:
    parsed = parse_currency(amount)
    if parsed is None:
        return ""
    text = format_currency(parsed)
    return text.split(".", 1)[0]


def _cents_part(amount: object) -> str:
    parsed = parse_currency(amount)
    if parsed is None:
        return ""
    text = format_currency(parsed)
    if "." not in text:
        return ""
    return text.split(".", 1)[1]


def is_echo_cents(amount: object) -> bool:
    """True when cents digits echo the dollars stem (222.22, 444.44)."""
    dollars = _dollars_part(amount)
    cents = _cents_part(amount)
    if not dollars or not cents or cents == "00":
        return False
    if len(dollars) >= 2 and dollars == cents:
        return True
    # Short echo: dollars ``44`` / cents ``44``, or trailing two dollars digits.
    if len(dollars) >= 2 and dollars[-2:] == cents:
        return True
    return False


def is_units_bleed_cents(amount: object) -> bool:
    """True when cents look like units/ruling bleed rather than typed cents."""
    cents = _cents_part(amount)
    if not cents or cents == "00":
        return False
    if cents in _BLEED_CENTS:
        return True
    return is_echo_cents(amount)


def cash_ruling_confirms_amount(
    amount: object, field_payload: dict | None = None
) -> bool:
    """True when a DI/Box 28 raw is ``$ dollars : cents`` matching ``amount``.

    Printed cents confirmed by cash ruling-split geometry are not units bleed
    (DJKH.002/005/010: ``7 $ 157 :07``, ``$ 222 |22``).
    """
    target = parse_currency(amount)
    if target is None or not isinstance(field_payload, dict):
        return False
    target_txt = format_currency(target)
    try:
        from packages.claim_evidence.line_charge_selector import _ruling_split_amount
    except Exception:  # noqa: BLE001
        return False
    rows: list[dict] = []
    if isinstance(field_payload.get("ranked_candidate"), dict):
        rows.append(field_payload["ranked_candidate"])
    rows.extend(
        row for row in (field_payload.get("alternatives") or []) if isinstance(row, dict)
    )
    rows.extend(
        row for row in (field_payload.get("candidates") or []) if isinstance(row, dict)
    )
    ocr_block = field_payload.get("ocr") if isinstance(field_payload.get("ocr"), dict) else {}
    rows.extend(
        row for row in (ocr_block.get("candidates") or []) if isinstance(row, dict)
    )
    residual = field_payload.get("azure_di_residual") or {}
    if isinstance(residual, dict):
        rows.append(residual)
    for row in rows:
        ocr = row.get("ocr_candidate") or row
        if not isinstance(ocr, dict):
            continue
        raw_text = str(ocr.get("raw_value") or ocr.get("value") or "")
        if "$" not in raw_text or not re.search(r"[:|/]", raw_text):
            continue
        ruled = _ruling_split_amount(raw_text)
        if ruled and ruled == target_txt:
            return True
    return False


def is_ruling_tail_extension(shorter: object, longer: object) -> bool:
    """True when ``longer`` is ``shorter`` plus one ruling-tail digit (1/4/5).

    Both amounts must be whole dollars (``.00``). The shorter stem must be at
    least two digits so ``5.00``/``51.00`` style noise does not collapse.
    """
    sa = parse_currency(shorter)
    sb = parse_currency(longer)
    if sa is None or sb is None:
        return False
    ta, tb = format_currency(sa), format_currency(sb)
    if not (ta.endswith(".00") and tb.endswith(".00")):
        return False
    a, b = _dollars_part(ta), _dollars_part(tb)
    if not a or not b or a == b or len(a) < 2 or len(b) < 2:
        return False
    if b.startswith(a) and len(b) == len(a) + 1 and b[-1] in {"1", "4", "5"}:
        return True
    return a.startswith(b) and len(a) == len(b) + 1 and a[-1] in {"1", "4", "5"}


def _variant(cand: dict) -> str:
    return str(cand.get("preprocessing_variant") or "").casefold()


def _is_ruling_variant(cand: dict) -> bool:
    return "dollars_ruling" in _variant(cand)


def _is_geometry_variant(cand: dict) -> bool:
    return "geometry_cents" in _variant(cand)


def _is_derived_variant(cand: dict) -> bool:
    v = _variant(cand)
    return "derived_from_observed_line" in v or "phase2-line-sum" in v


def collect_charge_candidates(
    *,
    primary: object = None,
    field_payload: dict | None = None,
    service_lines: list[dict] | None = None,
) -> list[tuple[str, str]]:
    """Return ``(amount, source_tag)`` pairs from Box 28 + line OCR shells."""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(raw: object, tag: str) -> None:
        parsed = parse_currency(raw)
        if parsed is None:
            return
        text = format_currency(parsed)
        if is_implausible_charge_total(text):
            return
        key = (text, tag)
        if key in seen:
            return
        seen.add(key)
        found.append((text, tag))

    if primary not in (None, ""):
        _add(primary, "primary")

    payloads: list[dict] = []
    if isinstance(field_payload, dict):
        payloads.append(field_payload)
        ocr = field_payload.get("ocr")
        if isinstance(ocr, dict):
            payloads.append(ocr)

    for payload in payloads:
        for cand in payload.get("candidates") or []:
            if not isinstance(cand, dict) or _is_derived_variant(cand):
                continue
            tag = (
                "ruling"
                if _is_ruling_variant(cand)
                else ("geometry" if _is_geometry_variant(cand) else "full")
            )
            _add(cand.get("value") or cand.get("raw_value"), tag)
        for row in (
            [payload.get("ranked_candidate")]
            if payload.get("ranked_candidate")
            else []
        ) + list(payload.get("alternatives") or []):
            if not row:
                continue
            ocr = row.get("ocr_candidate") or {}
            if _is_derived_variant(ocr):
                continue
            tag = (
                "ruling"
                if _is_ruling_variant(ocr)
                else ("geometry" if _is_geometry_variant(ocr) else "full")
            )
            _add(ocr.get("value") or ocr.get("raw_value"), tag)

    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        for key in ("charges", "charge_amount"):
            if line.get(key) not in (None, ""):
                _add(line.get(key), "line")
                break
        for cand in line.get("candidates") or []:
            if not isinstance(cand, dict) or _is_derived_variant(cand):
                continue
            tag = (
                "line_ruling"
                if _is_ruling_variant(cand)
                else (
                    "line_geometry" if _is_geometry_variant(cand) else "line_full"
                )
            )
            _add(cand.get("value") or cand.get("raw_value"), tag)

    return found


def prefer_safe_charge_amount(left: object, right: object) -> str | None:
    """Prefer bleed-safe amount between two readings.

    Untagged ruling-tail / digit-drop twins (``70`` vs ``701``, ``25`` vs
    ``251``) abstain — those need source tags in ``resolve_safe_charge_total``
    so we never collapse a real stem like ``251 → 25``. Same-dollar ``.00``
    preference is also tag-gated (integrity: no automatic rewrite).
    """
    a = parse_currency(left)
    b = parse_currency(right)
    if a is None and b is None:
        return None
    if a is None:
        return format_currency(b) if b is not None else None
    if b is None:
        return format_currency(a)
    ta, tb = format_currency(a), format_currency(b)
    if ta == tb:
        return ta

    # C2 without tags is ambiguous with digit-drop twins — abstain.
    if is_ruling_tail_extension(ta, tb):
        return None

    if is_decimal_place_shift(ta, tb):
        return None
    return None


def resolve_safe_charge_total(
    *,
    primary: object = None,
    field_payload: dict | None = None,
    service_lines: list[dict] | None = None,
) -> tuple[str | None, str]:
    """Select a precision-safe total or abstain.

    Returns ``(amount, reason)``. Applies tagged C1/C2 repairs from OCR
    candidates only — never invents Box 28 from a service-line Σ.
    """
    candidates = collect_charge_candidates(
        primary=primary,
        field_payload=field_payload,
        service_lines=service_lines,
    )
    if not candidates:
        if primary not in (None, ""):
            parsed = parse_currency(primary)
            if parsed is None or is_implausible_charge_total(primary):
                return None, "INVALID_PRIMARY"
            return format_currency(parsed), "PRIMARY_UNCHANGED"
        return None, "NO_CANDIDATES"

    primary_txt = None
    if parse_currency(primary) is not None:
        primary_txt = format_currency(parse_currency(primary))

    by_tag: dict[str, list[str]] = {}
    for amount, tag in candidates:
        by_tag.setdefault(tag, []).append(amount)

    full_amounts = [
        amt
        for tag, amounts in by_tag.items()
        if tag in _FULL_TAGS
        for amt in amounts
        if amt.endswith(".00")
    ]
    ruling_amounts = [
        amt
        for tag, amounts in by_tag.items()
        if tag in _RULING_TAGS
        for amt in amounts
    ]
    # OCR-observed amounts only — exclude bare "line" shells used for diagnosis.
    ocr_amounts = [
        amt
        for amt, tag in candidates
        if tag not in {"line"}
    ]

    # C2: full-window stem beats dollars-ruling that added trailing 1/4/5.
    # Only shrink when the *longer* form is ruling-tagged (or primary matches
    # that ruling). Never treat a shorter ruling crop as license to collapse
    # a longer primary (251 → 25).
    for full in full_amounts:
        fd = _dollars_part(full)
        if len(fd) < 2:
            continue
        for ruling in ruling_amounts:
            rd = _dollars_part(ruling)
            if not (
                rd.startswith(fd)
                and len(rd) == len(fd) + 1
                and rd[-1] in {"1", "4", "5"}
            ):
                continue
            if primary_txt in {None, ruling, full} or (
                primary_txt is not None and _dollars_part(primary_txt) == rd
            ):
                return full, "RULING_TAIL_TO_FULL_STEM"
        if primary_txt is not None:
            pd = _dollars_part(primary_txt)
            if (
                pd.startswith(fd)
                and len(pd) == len(fd) + 1
                and pd[-1] in {"1", "4", "5"}
                and any(_dollars_part(r) == pd for r in ruling_amounts)
            ):
                return full, "RULING_TAIL_TO_FULL_STEM"

    # C1: bleed cents → same-dollar .00 sibling from OCR (never from line Σ).
    # Cash ruling-split printed cents (``$ 222 |22``) are not units bleed.
    if primary_txt and is_units_bleed_cents(primary_txt):
        if cash_ruling_confirms_amount(primary_txt, field_payload):
            return primary_txt, "CASH_RULING_PRINTED_CENTS"
        dollars = _dollars_part(primary_txt)
        sibling = f"{dollars}.00"
        if sibling in ocr_amounts:
            return sibling, "BLEED_CENTS_TO_WHOLE_DOLLAR"
        # Whole-dollar service-line Σ with the same dollars is independent arithmetic
        # corroboration of the stem — prefer it over bleed cents (DJKH .32/.43).
        line_wholes = [
            amt
            for amt, tag in candidates
            if tag == "line" and amt == sibling
        ]
        if line_wholes:
            return sibling, "BLEED_CENTS_TO_LINE_SUM_WHOLE_DOLLAR"

    for amount in ocr_amounts:
        if not is_units_bleed_cents(amount):
            continue
        if cash_ruling_confirms_amount(amount, field_payload):
            if primary_txt in {amount, None}:
                return amount, "CASH_RULING_PRINTED_CENTS"
            continue
        sibling = f"{_dollars_part(amount)}.00"
        if sibling in ocr_amounts and primary_txt in {amount, sibling, None}:
            if primary_txt == sibling:
                return sibling, "PRIMARY_UNCHANGED"
            if primary_txt == amount:
                return sibling, "BLEED_CENTS_TO_WHOLE_DOLLAR"

    if primary_txt:
        return primary_txt, "PRIMARY_UNCHANGED"
    if len(set(full_amounts)) == 1:
        return full_amounts[0], "SAFE_CHARGE_FROM_CANDIDATES"
    # Discovery only when Box 28 missing: single OCR candidate, not line mix.
    box28_only = collect_charge_candidates(field_payload=field_payload)
    amounts = {amount for amount, _tag in box28_only}
    if len(amounts) == 1:
        return next(iter(amounts)), "UNVERIFIED_BOX28_CANDIDATE"
    return None, "NO_SAFE_PRIMARY"


_OPEN_SOURCE_CHARGE_ENGINES = frozenset(
    {"paddleocr", "rapidocr", "tesseract", "tesseract_digits"}
)


def dual_open_source_charge_agreement(
    chosen: object, candidates: list | None
) -> bool:
    """True when ≥2 distinct local OCR engines corroborate ``chosen`` exactly.

    Conflict-agent / Claude picks must not AUTO on a single paddle whitelist
    hit — that was the TRUE_STP monetary leak on DJKH/DJJM.
    """
    from packages.claim_evidence.line_sum_authority import amounts_corroborate

    engines: set[str] = set()
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        shell = (
            cand.get("ocr_candidate")
            if isinstance(cand.get("ocr_candidate"), dict)
            else cand
        )
        engine = str(shell.get("engine") or shell.get("engine_name") or "").casefold()
        if engine not in _OPEN_SOURCE_CHARGE_ENGINES:
            continue
        value = shell.get("value") or shell.get("raw_value")
        if amounts_corroborate(chosen, value):
            engines.add(engine)
    return len(engines) >= 2


def line_sum_corroborates_charge(
    chosen: object, service_lines: list | None
) -> bool:
    """True when observed service-line Σ equals ``chosen`` exactly."""
    from packages.claim_evidence.line_sum_authority import (
        amounts_corroborate,
        line_sum_total,
    )

    total = line_sum_total(service_lines)
    if total is None:
        return False
    return amounts_corroborate(chosen, total)


def authorize_conflict_agent_charge(
    chosen: object,
    *,
    candidates: list | None = None,
    field_payload: dict | None = None,
    service_lines: list | None = None,
) -> tuple[str | None, str]:
    """Gate LLM conflict-agent monetary picks before CLAIM_TOTAL AUTO.

    Returns ``(amount, reason)``. ``amount is None`` → fail-closed HITL.
    Never lets Claude/conflict-agent be sole monetary authority:
      - bleed/echo cents require an OCR whole-dollar sibling (or HITL)
      - otherwise need dual open-source engine agreement OR exact line Σ
      - L3: Claude+local printed bleed cents with DI ×100 soup may AUTO
      - L4: exact DI + vision/local partner corroboration may AUTO
    """
    parsed = parse_currency(chosen)
    if parsed is None or is_implausible_charge_total(chosen):
        return None, "CONFLICT_AGENT_INVALID_AMOUNT"

    text = format_currency(parsed)
    safe, safe_reason = resolve_safe_charge_total(
        primary=text,
        field_payload=field_payload,
        service_lines=None,
    )
    if safe_reason == "BLEED_CENTS_TO_WHOLE_DOLLAR" and safe:
        text = safe
    elif is_units_bleed_cents(text):
        # L3: Claude/gpt-4o + local agree on printed bleed cents; DI ×100 twin
        # is soup — do not require a .00 sibling (DJKH.030 ``251.43``).
        if _vision_local_confirms_bleed_cents(text, candidates):
            return text, "VISION_LOCAL_PRINTED_BLEED_CENTS"
        if cash_ruling_confirms_amount(text, field_payload):
            return text, "CASH_RULING_PRINTED_CENTS"
        # Observed bleed cents with no OCR .00 sibling — do not AUTO.
        return None, "BLEED_CENTS_UNCORROBORATED"

    if dual_open_source_charge_agreement(text, candidates):
        return text, "DUAL_OPEN_SOURCE_CHARGE_AGREEMENT"
    if line_sum_corroborates_charge(text, service_lines):
        return text, "LINE_SUM_CORROBORATES_CONFLICT_PICK"
    # L4: exact DI + (vision or local) on the conflict-agent pick.
    if _exact_di_partner_charge_agreement(text, candidates):
        return text, "BOX28_DI_PARTNER_CONFIRMS_CONFLICT_PICK"
    # EJGE cluster: Claude corroborates the agent pick; every dissenting local
    # is a strict underread (partial OCR), never a larger rival. Not sole LLM —
    # vision + listed rival resolution with underread scrap only.
    if _vision_corroborates_underread_locals(text, candidates):
        return text, "VISION_CORROBORATES_CONFLICT_PICK"
    return None, "CONFLICT_AGENT_SOLE_AUTHORITY"


def _vision_corroborates_underread_locals(
    chosen: object, candidates: list | None
) -> bool:
    """True when vision matches ``chosen`` and every local dissent is underread.

    EJGE.016/017/018/032: Claude ``300`` / ``250`` vs paddle ``29`` / ``12``.
    Rejects when any local is a larger / inflated rival of the pick.
    """
    from packages.claim_evidence.line_sum_authority import amounts_corroborate

    chosen_amt = parse_currency(chosen)
    if chosen_amt is None or chosen_amt <= 0:
        return False
    has_vision = False
    saw_local = False
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        shell = (
            cand.get("ocr_candidate")
            if isinstance(cand.get("ocr_candidate"), dict)
            else cand
        )
        engine = str(shell.get("engine") or shell.get("engine_name") or "").casefold()
        value = shell.get("value") or shell.get("raw_value")
        if any(tok in engine for tok in ("claude", "gpt4o", "gpt-4o", "anthropic")):
            if amounts_corroborate(chosen, value):
                has_vision = True
            continue
        if not any(tok in engine for tok in ("paddle", "rapid", "tesseract")):
            continue
        saw_local = True
        text = str(value or "").strip()
        if not text:
            continue
        if amounts_corroborate(chosen, value):
            continue
        other = parse_currency(value)
        if other is None:
            continue
        # Strict underread only — inflated locals are genuine rivals.
        if other >= chosen_amt:
            return False
    return has_vision and saw_local


def _vision_local_confirms_bleed_cents(
    chosen: object, candidates: list | None
) -> bool:
    """True when vision + local agree on bleed-cents ``chosen`` (DI may be ×100)."""
    from packages.claim_evidence.line_sum_authority import amounts_corroborate

    if not is_units_bleed_cents(chosen):
        return False
    has_vision = False
    has_local = False
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        shell = (
            cand.get("ocr_candidate")
            if isinstance(cand.get("ocr_candidate"), dict)
            else cand
        )
        engine = str(shell.get("engine") or shell.get("engine_name") or "").casefold()
        value = shell.get("value") or shell.get("raw_value")
        if not amounts_corroborate(chosen, value):
            continue
        if any(tok in engine for tok in ("claude", "gpt4o", "gpt-4o", "anthropic")):
            has_vision = True
        elif any(tok in engine for tok in ("paddle", "rapid", "tesseract")):
            has_local = True
    return has_vision and has_local


def _exact_di_partner_charge_agreement(
    chosen: object, candidates: list | None
) -> bool:
    """True when DI exact-matches ``chosen`` and vision or local also matches.

    Unlike ``box28_di_partner_confirmed``, DI scale/×100 twins do not count —
    that would AUTO inflated agent picks beside DI soup (DJKH.040).
    Vision+local alone is not DI-partner authority (that path is separate E4).
    """
    from packages.claim_evidence.line_sum_authority import amounts_corroborate

    families: set[str] = set()
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        shell = (
            cand.get("ocr_candidate")
            if isinstance(cand.get("ocr_candidate"), dict)
            else cand
        )
        engine = str(shell.get("engine") or shell.get("engine_name") or "").casefold()
        value = shell.get("value") or shell.get("raw_value")
        if not amounts_corroborate(chosen, value):
            continue
        if "document_intelligence" in engine or "azure_di" in engine or "azure_read" in engine:
            families.add("di")
        elif any(tok in engine for tok in ("claude", "gpt4o", "gpt-4o", "anthropic")):
            families.add("vision")
        elif any(tok in engine for tok in ("paddle", "rapid", "tesseract")):
            families.add("local")
    return "di" in families and bool(families & {"vision", "local"})


# ---------------------------------------------------------------------------
# Single monetary AUTO gate — one mint of CLAIM_TOTAL_CONFIRMED per claim.
# Priority (highest first). Callers must try_confirm in this order; first
# non-bleed success locks. Later paths keep diagnostic evidence only.
# ---------------------------------------------------------------------------
CONFIRM_PRIORITY: tuple[str, ...] = (
    "DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES",
    "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
    "GEOMETRY_UNDERREAD_WHOLE_DOLLAR_BOX28",
    "OPEN_SOURCE_DIGIT_DROP_FULLER_BOX28",
    "INCOMPLETE_UNIFORM_GRID_BOX28",
    "BOX28_LINE_SUM_CORROBORATED",
    "CLAIM_TOTAL_WITHIN_TOLERANCE",
    "DUAL_OPEN_SOURCE_CHARGE_AGREEMENT",
    "LINE_SUM_CORROBORATES_CONFLICT_PICK",
    "BOX28_DI_PARTNER_CONFIRMS_CONFLICT_PICK",
    "VISION_LOCAL_PRINTED_BLEED_CENTS",
    "CASH_RULING_PRINTED_CENTS",
    "CONFLICT_AGENT_FINANCIAL_RESOLVED",
    "LINE_TOTALS_CORROBORATED",
)

# Evidence code stamped on every successful mint so reconciliation requires the
# single-authority path instead of OR-ing FG ∪ line-sum ∪ derived ∪ DI.
CHARGE_TOTAL_AUTHORITY_CODE = "CHARGE_TOTAL_AUTHORITY"


def _priority_index(reason: str) -> int:
    try:
        return CONFIRM_PRIORITY.index(reason)
    except ValueError:
        # Unknown reasons sort after the known stack (weaker).
        return len(CONFIRM_PRIORITY)


@dataclass(frozen=True)
class ChargeTotalDecision:
    """Sole monetary AUTO decision for a claim."""

    amount: str | None
    auto: bool
    reason: str
    locked_by: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "amount": self.amount,
            "auto": self.auto,
            "reason": self.reason,
            "locked_by": self.locked_by,
        }


class ChargeTotalAuthoritySession:
    """Per-claim lock: at most one CLAIM_TOTAL_CONFIRMED mint.

    Bleed/echo cents are rejected at mint time (not only at reconciler AUTO).
    """

    def __init__(self) -> None:
        self._amount: str | None = None
        self._reason: str | None = None
        self._locked: bool = False
        self._rejects: list[tuple[str, str]] = []

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def amount(self) -> str | None:
        return self._amount

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def rejects(self) -> list[tuple[str, str]]:
        return list(self._rejects)

    def decision(self) -> ChargeTotalDecision:
        if self._locked and self._amount:
            return ChargeTotalDecision(
                amount=self._amount,
                auto=True,
                reason=self._reason or "CHARGE_TOTAL_AUTHORITY",
                locked_by=self._reason,
            )
        return ChargeTotalDecision(
            amount=None,
            auto=False,
            reason="CHARGE_TOTAL_HITL",
            locked_by=None,
        )

    def try_confirm(self, amount: object, reason: str) -> tuple[bool, str]:
        """Attempt to lock monetary AUTO for ``amount``.

        Returns ``(accepted, detail)``. Rejects bleed at mint after attempting
        whole-dollar repair; ignores weaker or duplicate confirms after lock.
        """
        parsed = parse_currency(amount)
        if parsed is None or is_implausible_charge_total(amount):
            detail = "INVALID_AMOUNT"
            self._rejects.append((reason, detail))
            return False, detail
        text = format_currency(parsed)
        if is_units_bleed_cents(text):
            # Cash ruling-split printed cents are not units bleed — allow mint.
            if reason != "CASH_RULING_PRINTED_CENTS":
                # Prefer same-dollar .00 stem when reason already implies line/OCR
                # whole-dollar corroboration; otherwise fail closed at mint.
                whole = f"{_dollars_part(text)}.00"
                if reason in {
                    "CLAIM_TOTAL_WITHIN_TOLERANCE",
                    "BOX28_LINE_SUM_CORROBORATED",
                    "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
                    "LINE_TOTALS_CORROBORATED",
                    "BLEED_CENTS_TO_WHOLE_DOLLAR",
                    "BLEED_CENTS_TO_LINE_SUM_WHOLE_DOLLAR",
                }:
                    # Caller must pass the repaired whole amount; bleed text alone
                    # never locks.
                    detail = "BLEED_CENTS_AT_MINT"
                    self._rejects.append((reason, detail))
                    return False, detail
                detail = "BLEED_CENTS_AT_MINT"
                self._rejects.append((reason, detail))
                return False, detail
            # else: fall through and lock CASH_RULING_PRINTED_CENTS
        if self._locked:
            if self._amount == text and self._reason == reason:
                return True, "ALREADY_LOCKED"
            detail = f"ALREADY_CONFIRMED_BY_{self._reason}"
            self._rejects.append((reason, detail))
            return False, detail
        self._amount = text
        self._reason = reason
        self._locked = True
        return True, reason


def repair_bleed_to_whole_dollar(
    amount: object,
    *,
    field_payload: dict | None = None,
    service_lines: list | None = None,
) -> tuple[str | None, str]:
    """Return whole-dollar repair for bleed cents, or (None, reason)."""
    return resolve_safe_charge_total(
        primary=amount,
        field_payload=field_payload,
        service_lines=service_lines,
    )


def new_charge_total_authority() -> ChargeTotalAuthoritySession:
    """Factory for a fresh per-claim monetary authority session."""
    return ChargeTotalAuthoritySession()
