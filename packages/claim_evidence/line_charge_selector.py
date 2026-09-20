"""Select printed Box 24F line charges from local OCR evidence only.

Selection never uses Box 28 or the line-sum total. Those are verification
inputs for later authority, not candidates for rewriting a row amount.

Disposition:
  SELECTED_LOCAL_CHARGE  — one currency-shaped charge-column amount wins
  AMBIGUOUS_LINE_CHARGE  — competing valid amounts
  UNREADABLE_LINE_CHARGE — no usable charge-column evidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from packages.claim_evidence.line_sum_authority import (
    format_currency,
    is_decimal_place_shift,
    parse_currency,
)
from packages.geometry_authority.cms1500_regions import (
    CMS1500_CHARGE_CENTS_X,
    CMS1500_LINE_COLUMNS,
    CMS1500_UNITS_X0,
    charge_region_verdict,
    is_pos_like_currency,
)

_LOCAL_ENGINES = frozenset({"paddleocr", "rapidocr"})
# Selection noise that is never a typed CMS charge on its own.
_SELECTION_NOISE = frozenset({"1.00", "0.00", "0.01", "0.10"})
_CONCAT_TAIL = frozenset({"0", "1", "4", "5"})


@dataclass(frozen=True)
class LineChargeSelection:
    disposition: str
    amount: str | None
    reason: str
    supporting_engines: tuple[str, ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "amount": self.amount,
            "reason": self.reason,
            "supporting_engines": list(self.supporting_engines),
            "rejected": [{"value": v, "reason": r} for v, r in self.rejected],
        }


def _engine_family(engine: object) -> str:
    text = str(engine or "").casefold()
    if "paddle" in text:
        return "paddleocr"
    if "rapid" in text:
        return "rapidocr"
    if "tesseract" in text:
        return "tesseract"
    if "gpt4o" in text or "gpt-4o" in text:
        return "azure_gpt4o_crop"
    return text


def _bbox_tuple(raw: object) -> tuple[float, float, float, float] | None:
    if isinstance(raw, dict) and raw.get("x0") is not None:
        try:
            return (
                float(raw["x0"]),
                float(raw["y0"]),
                float(raw["x1"]),
                float(raw["y1"]),
            )
        except (TypeError, ValueError, KeyError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
        except (TypeError, ValueError):
            return None
    return None


def _centre_x(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[0] + bbox[2]) / 2.0


def _centre_y(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[1] + bbox[3]) / 2.0


def _overlaps_units_column(bbox: tuple[float, float, float, float]) -> bool:
    # Majority of the crop sits in Box 24G units.
    x0, _, x1, _ = bbox
    width = max(1e-6, x1 - x0)
    overlap = max(0.0, min(x1, 1e9) - max(x0, CMS1500_UNITS_X0))
    return (overlap / width) >= 0.45


def _in_charge_column(bbox: tuple[float, float, float, float]) -> bool:
    verdict = charge_region_verdict(bbox, already_reference=True)
    if not verdict.authorised:
        return False
    if _overlaps_units_column(bbox):
        return False
    # Reject severely cents-clipped windows. Dollars-ruling crops often end
    # within a few px of the ruling (x1≈1161 vs cents@1155); requiring
    # cents+8 falsely marked dual-local 212.00 peers as OUTSIDE_CHARGE_COLUMN.
    if bbox[2] < CMS1500_CHARGE_CENTS_X - 12:
        return False
    cx = _centre_x(bbox)
    ch0, ch1 = CMS1500_LINE_COLUMNS["charges"]
    return ch0 <= cx <= ch1


def _is_selection_noise(amount: str) -> bool:
    if amount in _SELECTION_NOISE:
        return True
    # Classic POS codes that bleed from Box 24B (keep real charges like 81.00
    # when geometry already proved charge-column — handled separately).
    if amount in {"11.00", "12.00", "21.00", "22.00", "23.00"}:
        return True
    return False


def _dollars_digits(amount: str) -> str:
    parsed = parse_currency(amount)
    if parsed is None:
        return ""
    return format_currency(parsed).split(".", 1)[0]


def _looks_like_units_concat(amount: str, peers: set[str]) -> bool:
    """Reject ``6401.00`` / ``2601.00`` when a clean ``640.00`` / ``260.00`` peer exists."""
    if not amount.endswith(".00"):
        return False
    dollars = _dollars_digits(amount)
    if len(dollars) < 4 or dollars[-1] not in _CONCAT_TAIL:
        return False
    stem = dollars[:-1]
    stem_amount = f"{int(stem)}.00" if stem.isdigit() else None
    if stem_amount and stem_amount in peers:
        return True
    return False


def _looks_like_place_shift(amount: str, peers: set[str]) -> bool:
    """Reject ``4972.00`` when ``49.72`` is an observed peer."""
    digits = re.sub(r"\D", "", amount)
    if len(digits) < 4:
        return False
    if amount.endswith(".00") and len(_dollars_digits(amount)) >= 4:
        shifted = f"{digits[:-2]}.{digits[-2:]}"
        if shifted in peers and shifted != amount:
            return True
    amt = parse_currency(amount)
    if amt is None:
        return False
    for peer in peers:
        if peer == amount:
            continue
        peer_amt = parse_currency(peer)
        if peer_amt is None:
            continue
        # Only reject the inflated shell (×100), never the ruled smaller peer.
        if is_decimal_place_shift(amount, peer) and amt > peer_amt:
            return True
    return False


def _row_band_ok(
    bbox: tuple[float, float, float, float],
    row_y_band: tuple[float, float] | None,
) -> bool:
    if row_y_band is None:
        return True
    y0, y1 = row_y_band
    cy = _centre_y(bbox)
    # Allow a small vertical tolerance around the service-line strip.
    pad = max(8.0, 0.35 * (y1 - y0))
    return (y0 - pad) <= cy <= (y1 + pad)


_RULED_CENTS_RAW = re.compile(
    r"^\s*(\d{1,5})\s*[\n/| ]\s*(\d{2})\s*$"
)
_DOLLARS_CORRUPT_CENTS = re.compile(
    r"^\s*(\d{1,5})\s*[i:;.]\s*0{1,2}\s*$",
    re.IGNORECASE,
)


def _ruling_split_amount(raw: object) -> str | None:
    """Reconstruct dollars|cents ruling splits and dollars+units-bleed raws."""
    text = str(raw or "")
    match = _RULED_CENTS_RAW.match(text)
    if match:
        dollars, cents = match.group(1), match.group(2)
        try:
            return format_currency(parse_currency(f"{int(dollars)}.{cents}"))
        except (TypeError, ValueError):
            return None
    corrupt = _DOLLARS_CORRUPT_CENTS.match(text)
    if corrupt:
        try:
            return format_currency(parse_currency(f"{int(corrupt.group(1))}.00"))
        except (TypeError, ValueError):
            return None
    groups = re.findall(r"\d+", text)
    if len(groups) == 2 and 1 <= len(groups[0]) <= 5:
        dollars, tail = groups[0], groups[1]
        # Classic dollars|cents: ``34\\n25``.
        if len(tail) == 2 and ("\n" in text or "/" in text or "|" in text):
            try:
                return format_currency(parse_currency(f"{int(dollars)}.{tail}"))
            except (TypeError, ValueError):
                return None
        # Cents-first / RTL glue: OCR emits ``00\\n212`` (cents column then
        # dollars stem). Treating leading ``00`` as dollars yields SELECTION_NOISE
        # ``0.00`` and drops dual-local agreement on the real ``212.00``.
        if (
            ("\n" in text or "!" in text or " " in text)
            and dollars in {"0", "00"}
            and len(tail) >= 2
            and not (len(tail) == 2 and tail.isdigit())
        ):
            try:
                return format_currency(parse_currency(f"{int(tail)}.00"))
            except (TypeError, ValueError):
                return None
        # Dollars stem + units/ruling bleed (``212\\n100``, ``346 !04`` with
        # a longer junk tail): keep the leading dollars as whole dollars when
        # the tail is not a clean two-digit cents read.
        if (
            ("\n" in text or "!" in text or " " in text)
            and len(tail) >= 2
            and not (len(tail) == 2 and tail.isdigit() and "." in text)
        ):
            # ``346 !04`` → prefer not to invent .00 here; leave to peers.
            if len(tail) >= 3 or tail in {"100", "101", "104", "110"}:
                try:
                    return format_currency(parse_currency(f"{int(dollars)}.00"))
                except (TypeError, ValueError):
                    return None
    return None


def _raw_has_observed_decimal(raw: object) -> bool:
    return bool(re.search(r"\d+\.\d{2}", str(raw or "")))


def _is_bare_digit_soup(amount: str, raw: object) -> bool:
    """True for concatenated shells like ``4972`` / ``6401`` without a decimal."""
    if not amount.endswith(".00"):
        return False
    dollars = _dollars_digits(amount)
    if len(dollars) < 4:
        return False
    raw_text = str(raw or "")
    if _raw_has_observed_decimal(raw_text) or _ruling_split_amount(raw_text):
        return False
    # Raw is the same digit run (optionally with a trailing .00 we invented).
    digits = re.sub(r"\D", "", raw_text)
    return digits == dollars or digits == dollars + "00"


def _shaped_amount(cand: dict) -> str | None:
    raw = str(cand.get("raw_value") or cand.get("value") or "")
    ruled = _ruling_split_amount(raw)
    value_parsed = parse_currency(cand.get("value"))
    value_txt = format_currency(value_parsed) if value_parsed is not None else None
    # Ruled reconstruction wins unless it collapses to selection noise while the
    # upstream shaped value is a real charge (``00\\n212`` → ruled 0.00 vs 212.00).
    if ruled is not None:
        if not (
            _is_selection_noise(ruled)
            and value_txt
            and value_txt != ruled
            and not _is_selection_noise(value_txt)
        ):
            return ruled
    for key in ("value", "raw_value"):
        parsed = parse_currency(cand.get(key))
        if parsed is None:
            continue
        text = format_currency(parsed)
        # Prefer observed currency shape; digits-only locals still count when
        # already shaped upstream, but bare concat soup is filtered later.
        if re.search(r"\d+\.\d{2}", raw) or re.fullmatch(r"\d+\.\d{2}", text):
            return text
        if re.fullmatch(r"\d+\.\d{2}", text):
            return text
    return None


def _candidate_evidence_quality(cand: dict, amount: str) -> int:
    """Higher is better local evidence for the selected amount."""
    raw = cand.get("raw_value") or cand.get("value") or ""
    prep = str(
        cand.get("preprocessing_variant")
        or cand.get("evidence_reference")
        or ""
    )
    if "GEOMETRY_CENTS" in prep:
        return 3
    if _raw_has_observed_decimal(raw):
        return 3
    if _ruling_split_amount(raw) == amount:
        return 3
    if _is_bare_digit_soup(amount, raw):
        return 0
    return 1


def _geometry_cents_candidate_from_attempts(line: dict) -> dict | None:
    """Promote a GEOMETRY_CENTS attempt into a selectable local candidate.

    Service-line OCR often records geometry only on ``attempts`` while leaving
    bare-digit soup in ``candidates``. Without promotion, place-shifted shells
    like ``4972.00`` stay AMBIGUOUS even when geometry shaped ``49.77``.
    """
    region = _bbox_tuple(line.get("canonical_region") or line.get("ocr_region"))
    for attempt in line.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        reason = str(attempt.get("reason") or "")
        if "GEOMETRY_CENTS" not in reason or "UNDERREAD" in reason:
            continue
        obs = attempt.get("observation") or {}
        if not isinstance(obs, dict):
            continue
        shaped = (
            obs.get("canonical_monetary_value")
            or obs.get("shaped")
            or obs.get("text")
        )
        parsed = parse_currency(shaped)
        if parsed is None:
            continue
        amount = format_currency(parsed)
        if _is_selection_noise(amount):
            continue
        return {
            "engine": "rapidocr",
            "model_name": "geometry-cents",
            "model_version": "monetary-geometry",
            "preprocessing_variant": "GEOMETRY_CENTS",
            "value": amount,
            "raw_value": obs.get("raw_digit_sequence") or obs.get("text") or amount,
            "raw_confidence": 0.91,
            "evidence_reference": "GEOMETRY_CENTS",
            "bounding_box": (
                {
                    "x0": region[0],
                    "y0": region[1],
                    "x1": region[2],
                    "y1": region[3],
                }
                if region
                else None
            ),
        }
    return None


def select_line_charge(
    line: dict | None,
    *,
    row_y_band: tuple[float, float] | None = None,
) -> LineChargeSelection:
    """Choose one Box 24F charge from local OCR candidates on a single row."""
    if not isinstance(line, dict):
        return LineChargeSelection(
            "UNREADABLE_LINE_CHARGE", None, "NO_LINE"
        )

    rejected: list[tuple[str, str]] = []
    usable: list[tuple[str, str, dict]] = []  # amount, engine_family, cand

    line_region = _bbox_tuple(line.get("canonical_region") or line.get("ocr_region"))
    if row_y_band is None and line_region is not None:
        row_y_band = (line_region[1], line_region[3])

    candidates = list(line.get("candidates") or [])
    geo_cand = _geometry_cents_candidate_from_attempts(line)
    if geo_cand is not None:
        geo_amt = geo_cand.get("value")
        already = any(
            isinstance(c, dict)
            and parse_currency(c.get("value")) == parse_currency(geo_amt)
            and "GEOMETRY_CENTS"
            in str(c.get("preprocessing_variant") or c.get("evidence_reference") or "")
            for c in candidates
        )
        if not already:
            candidates.append(geo_cand)

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        family = _engine_family(cand.get("engine"))
        amount = _shaped_amount(cand)
        if amount is None:
            rejected.append((str(cand.get("value") or cand.get("raw_value") or ""), "UNSHAPED"))
            continue
        if _is_selection_noise(amount):
            rejected.append((amount, "SELECTION_NOISE"))
            continue
        # POS-like without charge-column geometry is not selectable.
        bbox = _bbox_tuple(cand.get("bounding_box")) or line_region
        if bbox is None:
            # No geometry: only keep local engines; still reject classic POS.
            if is_pos_like_currency(amount) and amount in {
                "11.00", "12.00", "21.00", "22.00", "23.00"
            }:
                rejected.append((amount, "POS_LIKE_NO_GEOMETRY"))
                continue
        else:
            if not _in_charge_column(bbox):
                rejected.append((amount, "OUTSIDE_CHARGE_COLUMN"))
                continue
            if not _row_band_ok(bbox, row_y_band):
                rejected.append((amount, "ROW_BASELINE_MISMATCH"))
                continue
            verdict = charge_region_verdict(bbox, already_reference=True)
            if verdict.reason == "CHARGE_GEOMETRY_POS_BLEED":
                rejected.append((amount, "POS_REGION_OVERLAP"))
                continue
        if family not in _LOCAL_ENGINES and family not in {"tesseract", "azure_gpt4o_crop"}:
            rejected.append((amount, f"ENGINE_{family or 'UNKNOWN'}"))
            continue
        usable.append((amount, family, cand))

    if not usable:
        return LineChargeSelection(
            "UNREADABLE_LINE_CHARGE",
            None,
            "NO_CHARGE_COLUMN_CANDIDATE",
            rejected=tuple(rejected[:12]),
        )

    peer_amounts = {amount for amount, _, _ in usable}
    filtered: list[tuple[str, str, dict, int]] = []
    soup_amounts: set[str] = set()
    for amount, family, cand in usable:
        if _looks_like_units_concat(amount, peer_amounts):
            rejected.append((amount, "UNITS_CONCAT_BLEED"))
            continue
        if _looks_like_place_shift(amount, peer_amounts):
            rejected.append((amount, "PLACE_SHIFT_SOUP"))
            continue
        quality = _candidate_evidence_quality(cand, amount)
        # Concatenated shells (6401 / 2601 / 4972) are never SELECTED alone —
        # keep them as conflict evidence for verification / HITL.
        if quality == 0:
            soup_amounts.add(amount)
            rejected.append((amount, "BARE_DIGIT_SOUP"))
            continue
        filtered.append((amount, family, cand, quality))

    if not filtered:
        soup_hint = sorted(soup_amounts)[0] if len(soup_amounts) == 1 else None
        return LineChargeSelection(
            "AMBIGUOUS_LINE_CHARGE" if soup_hint else "UNREADABLE_LINE_CHARGE",
            soup_hint,
            "ONLY_BLEED_OR_SOUP_CANDIDATES",
            rejected=tuple(rejected[:12]),
        )

    # Prefer dual local agreement on the same amount.
    by_amount: dict[str, set[str]] = {}
    quality_by_amount: dict[str, int] = {}
    for amount, family, _cand, quality in filtered:
        by_amount.setdefault(amount, set()).add(family)
        quality_by_amount[amount] = max(quality_by_amount.get(amount, 0), quality)

    dual_local = [
        amount
        for amount, families in by_amount.items()
        if len(families & _LOCAL_ENGINES) >= 2
    ]
    local_or_vision = [
        amount
        for amount, families in by_amount.items()
        if (families & _LOCAL_ENGINES)
        and (len(families) >= 2 or "azure_gpt4o_crop" in families)
    ]

    def _rank(amounts: list[str]) -> list[str]:
        return sorted(amounts, key=lambda a: (-quality_by_amount.get(a, 0), a))

    winners = _rank(dual_local) or _rank(local_or_vision)
    if not winners:
        # Single local engine only — ambiguous without a second reader.
        singles = sorted(by_amount.keys())
        if len(singles) == 1 and len(by_amount[singles[0]] & _LOCAL_ENGINES) >= 1:
            amount = singles[0]
            # Geometry-cents that defeated a place-shift / bare-digit shell is
            # authoritative even as a single local family (4972 soup vs 49.72).
            if quality_by_amount.get(amount, 0) >= 3 and any(
                reason in {
                    "PLACE_SHIFT_SOUP",
                    "BARE_DIGIT_SOUP",
                    "UNITS_CONCAT_BLEED",
                }
                for _, reason in rejected
            ):
                return LineChargeSelection(
                    "SELECTED_LOCAL_CHARGE",
                    amount,
                    "GEOMETRY_CENTS_PLACE_SHIFT_RESOLVED",
                    supporting_engines=tuple(sorted(by_amount[amount])),
                    rejected=tuple(rejected[:12]),
                )
            return LineChargeSelection(
                "AMBIGUOUS_LINE_CHARGE",
                amount,
                "SINGLE_LOCAL_ENGINE_ONLY",
                supporting_engines=tuple(sorted(by_amount[amount])),
                rejected=tuple(rejected[:12]),
            )
        return LineChargeSelection(
            "AMBIGUOUS_LINE_CHARGE",
            None,
            "NO_DUAL_LOCAL_AGREEMENT",
            rejected=tuple(rejected[:12]),
        )

    best_q = quality_by_amount.get(winners[0], 0)
    top = [a for a in winners if quality_by_amount.get(a, 0) == best_q]
    if len(set(top)) > 1:
        return LineChargeSelection(
            "AMBIGUOUS_LINE_CHARGE",
            None,
            "COMPETING_LOCAL_AMOUNTS",
            rejected=tuple(rejected[:12]),
        )

    amount = top[0]
    engines = tuple(sorted(by_amount[amount]))
    return LineChargeSelection(
        "SELECTED_LOCAL_CHARGE",
        amount,
        "DUAL_LOCAL_CHARGE_COLUMN"
        if len(set(engines) & _LOCAL_ENGINES) >= 2
        else "LOCAL_VISION_CHARGE_COLUMN",
        supporting_engines=engines,
        rejected=tuple(rejected[:12]),
    )


def apply_line_charge_selector(lines: list[dict] | None) -> list[dict]:
    """Apply ``select_line_charge`` to each service line; drop unreadable rows."""
    kept: list[dict] = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        selection = select_line_charge(line)
        updated = dict(line)
        updated["line_charge_selection"] = selection.to_dict()
        if selection.disposition == "SELECTED_LOCAL_CHARGE" and selection.amount:
            updated["charges"] = selection.amount
            updated["charge_amount"] = selection.amount
            updated["router_reason"] = (
                f"{line.get('router_reason') or ''}|LINE_CHARGE_SELECTOR:{selection.reason}"
            ).strip("|")
            kept.append(updated)
            continue
        if selection.disposition == "AMBIGUOUS_LINE_CHARGE":
            # Keep row for review / later verification, but do not promote a
            # bleed shell. Prefer selector amount hint when present.
            if selection.amount:
                updated["charges"] = selection.amount
                updated["charge_amount"] = selection.amount
            updated["line_charge_ambiguous"] = True
            updated["router_reason"] = (
                f"{line.get('router_reason') or ''}|LINE_CHARGE_AMBIGUOUS:{selection.reason}"
            ).strip("|")
            kept.append(updated)
            continue
        # UNREADABLE — drop from AUTO line set (verification will HITL).
        updated["charges"] = None
        updated["charge_amount"] = None
        updated["line_charge_unreadable"] = True
        updated["router_reason"] = (
            f"{line.get('router_reason') or ''}|LINE_CHARGE_UNREADABLE:{selection.reason}"
        ).strip("|")
        kept.append(updated)
    return kept
