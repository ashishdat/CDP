"""Evidence-based financial AUTO when printed Box 24F Σ equals Box 28 exactly.

``FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED`` is not threshold lowering. It fires
only when line charges were selected from charge-column evidence and the
printed total matches the arithmetic of those selections.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any

from packages.claim_evidence.box28_line_sum_authority import (
    build_box28_evidence,
    evaluate_parser_integrity,
)
from packages.claim_evidence.line_charge_selector import select_line_charge
from packages.claim_evidence.line_sum_authority import (
    format_currency,
    is_decimal_place_shift,
    is_implausible_charge_total,
    parse_currency,
)


@dataclass(frozen=True)
class FinancialGeometryDecision:
    confirmed: bool
    amount: str | None
    reason: str
    line_sum: str | None = None
    box28: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmed": self.confirmed,
            "amount": self.amount,
            "reason": self.reason,
            "line_sum": self.line_sum,
            "box28": self.box28,
            "details": self.details or {},
        }


def _line_selected_amount(line: dict) -> tuple[str | None, str]:
    selection = line.get("line_charge_selection")
    if isinstance(selection, dict) and selection.get("disposition") == "SELECTED_LOCAL_CHARGE":
        amount = selection.get("amount")
        if parse_currency(amount) is not None:
            return format_currency(parse_currency(amount)), "SELECTOR"
    # Fresh selection if OCR artifact predates the selector.
    result = select_line_charge(line)
    if result.disposition == "SELECTED_LOCAL_CHARGE" and result.amount:
        return result.amount, result.reason
    return None, result.disposition


def _digit_groups(*texts: object) -> set[str]:
    groups: set[str] = set()
    for text in texts:
        if text is None:
            continue
        for group in re.findall(r"\d+", str(text)):
            if group:
                groups.add(group)
                stripped = group.lstrip("0")
                if stripped:
                    groups.add(stripped)
    return groups


def _roi_digit_groups(
    box28_field_payload: dict | None,
    box28_observation: dict | None,
) -> set[str]:
    """Collect digit groups observed inside the Box 28 ROI across engines."""
    groups: set[str] = set()
    if isinstance(box28_observation, dict):
        groups |= _digit_groups(
            box28_observation.get("text"),
            box28_observation.get("raw_digit_sequence"),
            box28_observation.get("canonical_monetary_value"),
            *(box28_observation.get("raw_tokens") or []),
        )
        for attempt in box28_observation.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            obs = attempt.get("observation") or attempt
            if isinstance(obs, dict):
                groups |= _digit_groups(obs.get("text"), obs.get("raw_digit_sequence"))
            groups |= _digit_groups(attempt.get("text"), attempt.get("raw_value"))
    if not isinstance(box28_field_payload, dict):
        return groups
    rows = []
    if box28_field_payload.get("ranked_candidate"):
        rows.append(box28_field_payload["ranked_candidate"])
    rows.extend(box28_field_payload.get("alternatives") or [])
    rows.extend(box28_field_payload.get("candidates") or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        ocr = row.get("ocr_candidate") or row
        groups |= _digit_groups(ocr.get("value"), ocr.get("raw_value"))
    for attempt in box28_field_payload.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        obs = attempt.get("observation") or {}
        if isinstance(obs, dict):
            groups |= _digit_groups(obs.get("text"), obs.get("raw_digit_sequence"))
        groups |= _digit_groups(attempt.get("raw_value"), attempt.get("text"))
    return groups


def _same_roi_competing_soup(
    *,
    box_txt: str,
    alt_txt: str,
    alt_raw: object,
    box28_field_payload: dict | None,
    box28_observation: dict | None,
) -> bool:
    """True when confirmed Σ-matching Box 28 and a rival OCR share one ROI.

    Example: rapidocr ``135 00`` → ``135.00`` beside paddle ``43800`` → ``438.00``
    on the same Box 28 crop. Once arithmetic already agrees, the rival is soup.

    Clean money-shaped rivals (``270.00`` beside ``260.00``) stay conflicts.
    """
    conf_digits = re.sub(r"\D", "", box_txt)
    alt_digits = re.sub(r"\D", "", alt_txt)
    if not conf_digits or not alt_digits or conf_digits == alt_digits:
        return False
    raw = str(alt_raw or "")
    # A clean money form in the rival raw text is a real competing total.
    if re.search(r"\d+\.\d{2}", raw) or re.search(r"\d+\s+\d{2}\b", raw):
        return False
    box_dollars = box_txt.split(".", 1)[0]
    alt_dollars = alt_txt.split(".", 1)[0]
    groups = _roi_digit_groups(box28_field_payload, box28_observation)
    if not groups:
        return False

    def _present(full_digits: str, dollars: str) -> bool:
        candidates = {
            full_digits,
            full_digits.lstrip("0") or full_digits,
            dollars,
            dollars.lstrip("0") or dollars,
        }
        return any(token in groups for token in candidates if token)

    return _present(conf_digits, box_dollars) and _present(alt_digits, alt_dollars)


def _collect_box28_raw_texts(
    box28_field_payload: dict | None,
    box28_observation: dict | None,
    box28_amount: object = None,
) -> list[str]:
    texts: list[str] = []
    if box28_amount not in (None, ""):
        texts.append(str(box28_amount))
    if isinstance(box28_observation, dict):
        for key in ("text", "raw_digit_sequence", "canonical_monetary_value"):
            if box28_observation.get(key) not in (None, ""):
                texts.append(str(box28_observation[key]))
        for token in box28_observation.get("raw_tokens") or []:
            texts.append(str(token))
        for attempt in box28_observation.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            obs = attempt.get("observation") or {}
            if isinstance(obs, dict):
                texts.extend(
                    str(obs[k])
                    for k in ("text", "raw_digit_sequence")
                    if obs.get(k) not in (None, "")
                )
    if isinstance(box28_field_payload, dict):
        rows = []
        if box28_field_payload.get("ranked_candidate"):
            rows.append(box28_field_payload["ranked_candidate"])
        rows.extend(box28_field_payload.get("alternatives") or [])
        rows.extend(box28_field_payload.get("candidates") or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            ocr = row.get("ocr_candidate") or row
            for key in ("value", "raw_value"):
                if ocr.get(key) not in (None, ""):
                    texts.append(str(ocr[key]))
        for attempt in box28_field_payload.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            obs = attempt.get("observation") or {}
            if isinstance(obs, dict) and obs.get("text"):
                texts.append(str(obs["text"]))
    return texts


def _digits_match_with_single_junk(target_digits: str, candidate_digits: str) -> bool:
    """True when candidate equals target after deleting ≤1 digit either way."""
    if not target_digits or not candidate_digits:
        return False
    if candidate_digits == target_digits:
        return True
    if len(candidate_digits) == len(target_digits) + 1:
        for idx in range(len(candidate_digits)):
            if candidate_digits[:idx] + candidate_digits[idx + 1 :] == target_digits:
                return True
    if len(target_digits) == len(candidate_digits) + 1:
        for idx in range(len(target_digits)):
            if target_digits[:idx] + target_digits[idx + 1 :] == candidate_digits:
                return True
    return False


def _is_junk_digit_rival(confirmed: str, rival: str) -> bool:
    """True when rival digits are the confirmed total with ≤1 inserted junk digit."""
    conf = re.sub(r"\D", "", confirmed)
    riv = re.sub(r"\D", "", rival)
    if _digits_match_with_single_junk(conf, riv):
        return True
    # Dollars-stem junk (``2605`` beside confirmed ``260.00``).
    conf_dollars = confirmed.split(".", 1)[0]
    riv_dollars = rival.split(".", 1)[0]
    if conf_dollars and riv_dollars.startswith(conf_dollars):
        extra = riv_dollars[len(conf_dollars) :]
        if extra.isdigit() and 1 <= len(extra) <= 2:
            return True
    return False


def _raw_matches_sum_with_single_junk_digit(line_sum: str, raw_texts: list[str]) -> bool:
    """True when a Box 28 raw digit blob equals Σ after deleting ≤1 junk digit.

    Example: ``$400300`` → delete ``3`` → ``40000`` for Σ ``400.00``. Does not
    choose between two clean printed totals.
    """
    target = re.sub(r"\D", "", line_sum)
    if not target:
        return False
    for text in raw_texts:
        raw = str(text or "")
        # A clean money form that already disagrees is a real printed rival.
        if re.search(r"\d+\.\d{2}", raw):
            parsed = parse_currency(raw)
            if parsed is not None and format_currency(parsed) != line_sum:
                continue
        digits = re.sub(r"\D", "", raw)
        if not digits:
            continue
        if _digits_match_with_single_junk(target, digits):
            return True
    return False


def _same_stem_cents_twin(box_txt: str, line_sum: str) -> bool:
    """True when Box 28 and Σ share dollars and differ by ≤ $1.00 (OCR twin)."""
    box = parse_currency(box_txt)
    total = parse_currency(line_sum)
    if box is None or total is None:
        return False
    if box_txt.split(".", 1)[0] != line_sum.split(".", 1)[0]:
        return False
    return abs(box - total) <= Decimal("1.00")


def evaluate_financial_geometry_arithmetic(
    *,
    box28_amount: object,
    service_lines: list[dict] | None,
    box28_field_payload: dict | None = None,
    box28_region: object = None,
    box28_observation: dict | None = None,
) -> FinancialGeometryDecision:
    """Confirm total_charge when selected Box 24F Σ equals Box 28 exactly."""
    lines = [ln for ln in (service_lines or []) if isinstance(ln, dict)]
    if not lines:
        return FinancialGeometryDecision(False, None, "NO_SERVICE_LINES")

    selected: list[str] = []
    details_rows: list[dict[str, Any]] = []
    for line in lines:
        amount, reason = _line_selected_amount(line)
        details_rows.append({"amount": amount, "reason": reason})
        if amount is None:
            selection = line.get("line_charge_selection")
            disposition = (
                selection.get("disposition")
                if isinstance(selection, dict)
                else reason
            )
            # Ambiguous / unreadable rows stay out of Σ — they must not veto
            # confirmation of already-selected clean lines against Box 28.
            if disposition in {
                "AMBIGUOUS_LINE_CHARGE",
                "UNREADABLE_LINE_CHARGE",
            }:
                continue
            # Blank / unreadable active rows with procedure ink still block.
            if any(
                str(line.get(k) or "").strip()
                for k in ("procedure_code", "cpt", "charges", "charge_amount")
            ):
                return FinancialGeometryDecision(
                    False,
                    None,
                    "LINE_NOT_SELECTED",
                    details={"rows": details_rows},
                )
            continue
        selected.append(amount)

    if not selected:
        return FinancialGeometryDecision(False, None, "NO_SELECTED_LINES")

    total = sum((parse_currency(a) or Decimal(0) for a in selected), Decimal(0))
    line_sum = format_currency(total)

    box = parse_currency(box28_amount)
    if box is None or is_implausible_charge_total(box28_amount):
        return FinancialGeometryDecision(
            False, None, "BOX28_UNPARSED", line_sum=line_sum, details={"rows": details_rows}
        )
    box_txt = format_currency(box)
    if is_decimal_place_shift(box_txt, line_sum):
        return FinancialGeometryDecision(
            False,
            None,
            "DECIMAL_SHIFT_CONFLICT",
            line_sum=line_sum,
            box28=box_txt,
            details={"rows": details_rows},
        )
    if box != total:
        raw_texts = _collect_box28_raw_texts(
            box28_field_payload, box28_observation, box28_amount
        )
        if _raw_matches_sum_with_single_junk_digit(line_sum, raw_texts):
            return FinancialGeometryDecision(
                True,
                line_sum,
                "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
                line_sum=line_sum,
                box28=line_sum,
                details={
                    "rows": details_rows,
                    "box28_raw_junk_digit_relieved": True,
                    "ocr_box28": box_txt,
                    "raw_texts": raw_texts[:8],
                },
            )
        # Same-stem OCR twins (``346.04`` beside Σ ``346.00``) are not true
        # arithmetic conflicts — keep the printed Box 28 amount.
        if _same_stem_cents_twin(box_txt, line_sum):
            return FinancialGeometryDecision(
                True,
                box_txt,
                "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
                line_sum=line_sum,
                box28=box_txt,
                details={
                    "rows": details_rows,
                    "same_stem_cents_twin": True,
                    "line_sum": line_sum,
                },
            )
        return FinancialGeometryDecision(
            False,
            None,
            "ARITHMETIC_MISMATCH",
            line_sum=line_sum,
            box28=box_txt,
            details={"rows": details_rows},
        )

    # Box 28 must show observed decimal / glyph integrity — not a reconstructed shell.
    box28 = build_box28_evidence(
        amount=box_txt,
        field_payload=box28_field_payload,
        region=box28_region,
        observation=box28_observation,
    )
    if not box28.integrity.passed:
        # Fall back to raw observation / amount token integrity.
        raw = ""
        if isinstance(box28_observation, dict):
            raw = str(
                box28_observation.get("text")
                or box28_observation.get("raw_digit_sequence")
                or ""
            )
        if not raw:
            raw = str(box28_amount)
        integrity = evaluate_parser_integrity(amount=box_txt, raw_digit_sequence=raw)
        if not integrity.passed:
            # Soft path: printed amount already equals selected Σ exactly and the
            # raw/token text contains an observed decimal for that amount. Glyph
            # mapping failures must not block already-agreeing arithmetic.
            observed_decimal = bool(
                re.search(r"\d+\.\d{2}", str(raw))
                or re.search(r"\d+\.\d{2}", str(box28_amount or ""))
            )
            if not (
                observed_decimal
                and parse_currency(box_txt) == total
                and not is_decimal_place_shift(box_txt, line_sum)
            ):
                return FinancialGeometryDecision(
                    False,
                    None,
                    "BOX28_GEOMETRY_FAILED",
                    line_sum=line_sum,
                    box28=box_txt,
                    details={
                        "rows": details_rows,
                        "integrity": box28.integrity.rejection_reason,
                        "fallback": integrity.rejection_reason,
                    },
                )

    # Conflicting currency-shaped Box 28 competitors that are not place-shift
    # noise of the confirmed amount stay HITL.
    if isinstance(box28_field_payload, dict):
        for row in (
            [box28_field_payload.get("ranked_candidate")]
            if box28_field_payload.get("ranked_candidate")
            else []
        ) + list(box28_field_payload.get("alternatives") or []):
            if not row:
                continue
            ocr = row.get("ocr_candidate") or {}
            variant = str(ocr.get("preprocessing_variant") or "").casefold()
            if "derived_from_observed_line" in variant or "phase2-line-sum" in variant:
                continue
            alt = parse_currency(ocr.get("value") or ocr.get("raw_value"))
            if alt is None:
                continue
            alt_txt = format_currency(alt)
            if alt_txt == box_txt:
                continue
            if is_decimal_place_shift(alt_txt, box_txt):
                continue
            if is_implausible_charge_total(alt_txt):
                continue
            # Same-stem OCR twins (1160.40 beside confirmed 1160.00) are not
            # true financial conflicts like 2605 vs 2601 or 49.72 vs 4972.
            box_dollars = box_txt.split(".", 1)[0]
            alt_dollars = alt_txt.split(".", 1)[0]
            if box_dollars == alt_dollars and abs(alt - box) <= Decimal("1.00"):
                continue
            # Ruling-split / fragment of the already-confirmed amount
            # (``25.00`` beside confirmed ``34.25``) is not a competing total.
            if box == total:
                conf_digits = re.sub(r"\D", "", box_txt)
                alt_digits = re.sub(r"\D", "", alt_txt)
                alt_core = alt_digits.rstrip("0") or alt_digits
                if (
                    conf_digits
                    and alt_core
                    and len(alt_core) <= len(conf_digits)
                    and alt_core in conf_digits
                ):
                    continue
                # Junk-digit / dollars-stem rivals (``2605`` beside ``260.00``).
                if _is_junk_digit_rival(box_txt, alt_txt):
                    continue
                # Same-ROI dollars stem with junk tail (``34 125`` → ``125.00``).
                raw_groups = re.findall(r"\d+", str(ocr.get("raw_value") or ""))
                if box_dollars in raw_groups and alt_txt != box_txt:
                    continue
                # Competing OCR from the same Box 28 crop (``135 00`` vs ``43800``)
                # is soup once Σ already matches the confirmed printed total.
                if _same_roi_competing_soup(
                    box_txt=box_txt,
                    alt_txt=alt_txt,
                    alt_raw=ocr.get("raw_value"),
                    box28_field_payload=box28_field_payload,
                    box28_observation=box28_observation,
                ):
                    continue
            # Near-miss dollars that are not the confirmed total → conflict HITL.
            if abs(alt - box) > Decimal("0.01"):
                return FinancialGeometryDecision(
                    False,
                    None,
                    "CONFLICTING_BOX28_CANDIDATE",
                    line_sum=line_sum,
                    box28=box_txt,
                    details={"conflict": alt_txt, "rows": details_rows},
                )

    return FinancialGeometryDecision(
        True,
        box_txt,
        "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
        line_sum=line_sum,
        box28=box_txt,
        details={"rows": details_rows},
    )
