"""Classify Box 28 ROI blankness — OCR-empty alone is never confirmed blank."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from packages.claim_evidence.line_sum_authority import format_currency, parse_currency
from packages.image_evidence.analyzer import InkDisposition, analyze_roi


class Box28Blankness(StrEnum):
    CONFIRMED_BLANK = "CONFIRMED_BLANK"
    INK_PRESENT_UNREADABLE = "INK_PRESENT_UNREADABLE"
    ROI_UNUSABLE = "ROI_UNUSABLE"
    INK_OBSERVED = "INK_OBSERVED"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True)
class Box28BlanknessDecision:
    status: Box28Blankness
    reason: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "details": dict(self.details),
        }


def _currency_shaped_candidates(field_payload: dict | None) -> list[str]:
    found: list[str] = []
    if not isinstance(field_payload, dict):
        return found
    rows = []
    if field_payload.get("ranked_candidate"):
        rows.append(field_payload["ranked_candidate"])
    rows.extend(field_payload.get("alternatives") or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        ocr = row.get("ocr_candidate") or row
        text = ocr.get("value") or ocr.get("raw_value")
        if _is_box28_label_contamination(text):
            continue
        if parse_currency(text) is not None:
            found.append(str(text))
    for cand in field_payload.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        text = cand.get("value") or cand.get("raw_value")
        if _is_box28_label_contamination(text):
            continue
        if parse_currency(text) is not None:
            found.append(str(text))
    return found


def _is_box28_label_contamination(text: object) -> bool:
    """True when OCR is the Box 28 caption / ruling, not a printed total."""
    raw = str(text or "")
    upper = raw.upper()
    if "TOTAL CHARGE" in upper or "TOTAL CHARGES" in upper:
        return True
    # Bare form-index digit next to the caption (``8.TOTAL CHARGE`` / ``2!``).
    compact = "".join(ch for ch in upper if ch.isalnum())
    if compact in {"8", "28", "2", "8TOTALCHARGE", "28TOTALCHARGE"}:
        return True
    # Lone box-index amount soup (``8.00``) is not a claim total.
    amount = parse_currency(raw)
    if amount is not None and amount in {parse_currency("8.00"), parse_currency("2.00"), parse_currency("28.00")}:
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits in {"8", "2", "28", "800", "200", "2800"}:
            return True
    return False


def _is_llm_box_engine(engine: object) -> bool:
    name = str(engine or "").casefold()
    return any(token in name for token in ("claude", "gpt", "openai", "anthropic"))


def _raw_contains_distinct_charge(raw: object, amount: Decimal) -> bool:
    """True when caption OCR also holds a different plausible charge.

    ``TOTAL CHARGE 1200; 00 23`` still contains 1200, so the shaped ``23.00``
    must not be discarded — a short line sum cannot ignore that box.
    """
    for run in re.findall(r"\d{3,}", str(raw or "")):
        dollars = Decimal(run)
        if dollars >= 100 and dollars != amount:
            return True
        if len(run) >= 3:
            cents = Decimal(f"{run[:-2]}.{run[-2:]}")
            if cents >= 100 and cents != amount:
                return True
    return False


def is_caption_index_bleed(raw: object, value: object) -> bool:
    """True when a shaped Box 28 amount is the caption or the next box index.

    ``8. TOTAL CHARGE\\n29`` → ``29.00`` is box 29, not the printed total.
    Amounts of $100 or more stay charges (``TOTAL CHARGE $ 175.00``).
    A caption string that also contains a different ≥$100 run stays as well.
    """
    blob_raw = str(raw or "")
    blob_val = str(value or "")
    if not (
        _is_box28_label_contamination(blob_raw)
        or _is_box28_label_contamination(blob_val)
    ):
        return False
    amount = parse_currency(blob_val)
    if amount is None:
        amount = parse_currency(blob_raw)
    if amount is None:
        return True
    if amount >= Decimal("100"):
        return False
    return not _raw_contains_distinct_charge(blob_raw, amount)


def caption_only_bleed_amounts(field_payload: dict | None) -> set[str]:
    """Shaped amounts that exist only as caption/index bleed or an LLM echo of it.

    A non-LLM read of the same amount whose raw is not caption bleed keeps the
    amount (real Box 28 ink). ``17500`` with no caption is never in this set.
    """
    if not isinstance(field_payload, dict):
        return set()
    rows: list[dict] = []
    if isinstance(field_payload.get("ranked_candidate"), dict):
        rows.append(field_payload["ranked_candidate"])
    rows.extend(row for row in (field_payload.get("alternatives") or []) if isinstance(row, dict))
    rows.extend(row for row in (field_payload.get("candidates") or []) if isinstance(row, dict))
    bleed: set[str] = set()
    clean: set[str] = set()
    for row in rows:
        ocr = row.get("ocr_candidate") or row
        if not isinstance(ocr, dict):
            continue
        amount = parse_currency(ocr.get("value"))
        if amount is None:
            continue
        key = format_currency(amount)
        if is_caption_index_bleed(ocr.get("raw_value"), ocr.get("value")):
            bleed.add(key)
            continue
        if _is_llm_box_engine(ocr.get("engine")):
            continue
        clean.add(key)
    return bleed - clean


def cents_column_fragment_amounts(
    field_payload: dict | None,
    *,
    line_total: object = None,
) -> set[str]:
    """Amounts that are only the cents half of a fuller Box 28 / line peer.

    Azure DI ``39.00`` from ``$ 97|39`` beside Claude / line-sum ``97.39`` must
    not rank as the Box 28 winner or veto ``SINGLE_LINE_GPT4O_LOCAL``.
    """
    from packages.claim_evidence.line_sum_authority import is_cents_column_fragment

    if not isinstance(field_payload, dict):
        return set()
    amounts: set[str] = set()
    if parse_currency(line_total) is not None:
        amounts.add(format_currency(parse_currency(line_total)))
    rows: list[dict] = []
    if isinstance(field_payload.get("ranked_candidate"), dict):
        rows.append(field_payload["ranked_candidate"])
    rows.extend(row for row in (field_payload.get("alternatives") or []) if isinstance(row, dict))
    rows.extend(row for row in (field_payload.get("candidates") or []) if isinstance(row, dict))
    for residual_key in ("gpt4o_crop_residual", "azure_di_residual"):
        residual = field_payload.get(residual_key) or {}
        if isinstance(residual, dict) and parse_currency(residual.get("value")) is not None:
            amounts.add(format_currency(parse_currency(residual.get("value"))))
    agent = field_payload.get("financial_conflict_agent") or field_payload.get("conflict_agent") or {}
    if isinstance(agent, dict) and parse_currency(agent.get("chosen") or agent.get("value")) is not None:
        amounts.add(
            format_currency(parse_currency(agent.get("chosen") or agent.get("value")))
        )
    for row in rows:
        ocr = row.get("ocr_candidate") or row
        if not isinstance(ocr, dict):
            continue
        amount = parse_currency(ocr.get("value"))
        if amount is None:
            continue
        amounts.add(format_currency(amount))
    fragments: set[str] = set()
    for candidate in amounts:
        for peer in amounts:
            if candidate == peer:
                continue
            if is_cents_column_fragment(candidate, peer):
                fragments.add(candidate)
    return fragments


_DI_RAW_AMOUNT_TOKEN = re.compile(
    r"(?<!\d)(\d{1,6}(?:\.\d{2})?)(?!\d)"
)


def _trusted_box28_amounts(
    field_payload: dict | None,
    *,
    line_total: object = None,
) -> set[str]:
    """Line Σ / Claude / conflict-agent amounts that may own Box 28."""
    trusted: set[str] = set()
    if parse_currency(line_total) is not None:
        trusted.add(format_currency(parse_currency(line_total)))
    if not isinstance(field_payload, dict):
        return trusted
    agent = field_payload.get("financial_conflict_agent") or field_payload.get("conflict_agent") or {}
    if isinstance(agent, dict):
        chosen = parse_currency(agent.get("chosen") or agent.get("value"))
        if chosen is not None:
            trusted.add(format_currency(chosen))
    for residual_key in ("gpt4o_crop_residual",):
        residual = field_payload.get(residual_key) or {}
        if isinstance(residual, dict) and parse_currency(residual.get("value")) is not None:
            trusted.add(format_currency(parse_currency(residual.get("value"))))
    for row in (field_payload.get("candidates") or []):
        if not isinstance(row, dict):
            continue
        ocr = row.get("ocr_candidate") or row
        eng = str(ocr.get("engine") or "").casefold()
        if not any(token in eng for token in ("claude", "anthropic", "gpt4o", "gpt-4o")):
            continue
        amount = parse_currency(ocr.get("value"))
        if amount is not None:
            trusted.add(format_currency(amount))
    return trusted


def di_multi_token_rival_amounts(
    field_payload: dict | None,
    *,
    line_total: object = None,
) -> set[str]:
    """DI amounts that picked the wrong token from a multi-amount raw crop.

    DJKH.048: raw ``70 100 $`` shaped as ``100.00`` while Claude / line Σ /
    conflict agent agree on ``70.00``. The ``100`` token is not Box 28 ink.
    """
    if not isinstance(field_payload, dict):
        return set()
    trusted = _trusted_box28_amounts(field_payload, line_total=line_total)
    if not trusted:
        return set()
    rivals: set[str] = set()

    def _consider(engine: object, value: object, raw: object) -> None:
        eng = str(engine or "").casefold()
        if "document_intelligence" not in eng and "azure_di" not in eng:
            # Residual meta has no engine — allow when called from DI residual.
            if eng and "azure" not in eng:
                return
        amount = parse_currency(value)
        if amount is None:
            return
        shaped = format_currency(amount)
        if shaped in trusted:
            return
        tokens: set[str] = set()
        for match in _DI_RAW_AMOUNT_TOKEN.finditer(str(raw or "")):
            token_amt = parse_currency(match.group(1))
            if token_amt is None:
                continue
            tokens.add(format_currency(token_amt))
        if len(tokens) < 2:
            return
        if shaped not in tokens:
            return
        if tokens & trusted:
            rivals.add(shaped)

    residual = field_payload.get("azure_di_residual") or {}
    if isinstance(residual, dict) and residual.get("currency_shaped"):
        # Residual often lacks raw; use candidate raws that share the value.
        _consider(
            "azure_document_intelligence_read",
            residual.get("value"),
            residual.get("raw_value") or residual.get("value"),
        )
    rows: list[dict] = []
    if isinstance(field_payload.get("ranked_candidate"), dict):
        rows.append(field_payload["ranked_candidate"])
    rows.extend(row for row in (field_payload.get("alternatives") or []) if isinstance(row, dict))
    rows.extend(row for row in (field_payload.get("candidates") or []) if isinstance(row, dict))
    for row in rows:
        ocr = row.get("ocr_candidate") or row
        if not isinstance(ocr, dict):
            continue
        _consider(ocr.get("engine"), ocr.get("value"), ocr.get("raw_value"))
        # When residual value matches this DI candidate, attach its raw.
        if (
            isinstance(residual, dict)
            and parse_currency(residual.get("value")) is not None
            and parse_currency(ocr.get("value")) == parse_currency(residual.get("value"))
            and "document_intelligence" in str(ocr.get("engine") or "").casefold()
        ):
            _consider(
                ocr.get("engine"),
                residual.get("value"),
                ocr.get("raw_value"),
            )
    return rivals


def ruling_split_junk_insert_amounts(
    field_payload: dict | None,
    *,
    line_total: object = None,
) -> set[str]:
    """Digit-soup amounts that insert one junk digit into a ``$ dollars : cents`` read.

    DJKH.002: DI raw ``7 $ 157 :07`` → ``157.07``; paddle ``1571.07`` from
    ``157107`` is concat soup, not a second Box 28 total. Requires a cash
    ruling-split (``$`` + ``:``/``|``) so bare DI ``200`` vs paddle ``2001``
    (DJKN.005) stays a real place-shift conflict.
    """
    del line_total  # geometric confirmation comes from raw ruling-split only
    if not isinstance(field_payload, dict):
        return set()
    from packages.claim_evidence.financial_geometry_authority import (
        _digits_match_with_single_junk,
    )
    from packages.claim_evidence.line_charge_selector import _ruling_split_amount

    geometric: set[str] = set()
    shaped_rows: list[str] = []

    def _consume(value: object, raw: object) -> None:
        raw_text = str(raw or "")
        ruled = _ruling_split_amount(raw_text)
        # Cash ruling only — ``$ 157 :07`` / ``$ 222 |22``, not bare ``34\\n25``.
        if ruled and "$" in raw_text and re.search(r"[:|/]", raw_text):
            geometric.add(ruled)
        amount = parse_currency(value)
        if amount is not None:
            shaped_rows.append(format_currency(amount))

    residual = field_payload.get("azure_di_residual") or {}
    if isinstance(residual, dict):
        _consume(residual.get("value"), residual.get("raw_value") or residual.get("value"))
    rows: list[dict] = []
    if isinstance(field_payload.get("ranked_candidate"), dict):
        rows.append(field_payload["ranked_candidate"])
    rows.extend(row for row in (field_payload.get("alternatives") or []) if isinstance(row, dict))
    rows.extend(row for row in (field_payload.get("candidates") or []) if isinstance(row, dict))
    for row in rows:
        ocr = row.get("ocr_candidate") or row
        if not isinstance(ocr, dict):
            continue
        _consume(ocr.get("value"), ocr.get("raw_value"))

    rivals: set[str] = set()
    for shaped in shaped_rows:
        if shaped in geometric:
            continue
        riv_digits = re.sub(r"\D", "", shaped)
        for geo in geometric:
            conf_digits = re.sub(r"\D", "", geo)
            if len(riv_digits) != len(conf_digits) + 1:
                continue
            if _digits_match_with_single_junk(conf_digits, riv_digits):
                rivals.add(shaped)
                break
    return rivals


def box28_junk_winner_amounts(
    field_payload: dict | None,
    *,
    line_total: object = None,
) -> set[str]:
    """Caption bleed, cents-column fragments, and DI multi-token rivals."""
    return (
        caption_only_bleed_amounts(field_payload)
        | cents_column_fragment_amounts(field_payload, line_total=line_total)
        | di_multi_token_rival_amounts(field_payload, line_total=line_total)
        | ruling_split_junk_insert_amounts(field_payload, line_total=line_total)
    )


def _payload_is_label_only_or_empty(
    field_payload: dict | None,
    observation: dict | None,
) -> bool:
    """True when every OCR observation is empty or Box 28 caption contamination."""
    texts: list[str] = []
    if isinstance(observation, dict):
        for key in ("text", "raw_digit_sequence", "canonical_monetary_value"):
            if observation.get(key) not in (None, ""):
                texts.append(str(observation[key]))
    if isinstance(field_payload, dict):
        rows = []
        if field_payload.get("ranked_candidate"):
            rows.append(field_payload["ranked_candidate"])
        rows.extend(field_payload.get("alternatives") or [])
        rows.extend(field_payload.get("candidates") or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            ocr = row.get("ocr_candidate") or row
            for key in ("value", "raw_value"):
                if ocr.get(key) not in (None, ""):
                    texts.append(str(ocr[key]))
        for attempt in field_payload.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            obs = attempt.get("observation") or {}
            if isinstance(obs, dict) and obs.get("text"):
                texts.append(str(obs["text"]))
    if not texts:
        return False  # no OCR at all — need ROI ink analysis, not label-only blank
    return all(
        (not str(t).strip()) or _is_box28_label_contamination(t) for t in texts
    )


def _image_evidence_dict(
    field_payload: dict | None,
    observation: dict | None,
) -> dict[str, Any] | None:
    for source in (field_payload, observation):
        if not isinstance(source, dict):
            continue
        for key in ("image_evidence", "roi_image_evidence", "roi_evidence"):
            raw = source.get(key)
            if isinstance(raw, dict) and (
                raw.get("disposition") is not None or raw.get("ink_density") is not None
            ):
                return raw
        # Cascade / attempt payloads sometimes nest evidence.
        for attempt in source.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            for key in ("evidence", "image_evidence", "roi_evidence"):
                raw = attempt.get(key)
                if isinstance(raw, dict) and raw.get("disposition") is not None:
                    return raw
    return None


def classify_box28_blankness(
    *,
    box28_amount: object = None,
    field_payload: dict | None = None,
    observation: dict | None = None,
    roi_image: object = None,
    region: object = None,
) -> Box28BlanknessDecision:
    """Map Box 28 ROI state to confirmed-blank / unreadable / unusable.

    An OCR-empty result alone is never ``CONFIRMED_BLANK``. Confirmed blankness
    requires ROI ink analysis (density, connected components, ruling removal).
    """
    details: dict[str, Any] = {}
    currency = _currency_shaped_candidates(field_payload)
    amount_is_label = _is_box28_label_contamination(box28_amount)
    # Only treat box28_amount as amount-ink when it is not caption contamination.
    if (
        parse_currency(box28_amount) is not None
        and not amount_is_label
        and str(box28_amount) not in currency
    ):
        currency.append(str(box28_amount))
    details["currency_shaped_candidates"] = currency[:8]

    # Caption / ruling OCR only (``8.TOTAL CHARGE``) is confirmed blank — do this
    # before trusting a polluted normalized amount that is not in the payload.
    if _payload_is_label_only_or_empty(field_payload, observation):
        return Box28BlanknessDecision(
            Box28Blankness.CONFIRMED_BLANK,
            "BOX28_LABEL_ONLY_NO_AMOUNT_INK",
            details,
        )

    # Currency-shaped OCR means ink was observed — never confirmed blank.
    if currency:
        return Box28BlanknessDecision(
            Box28Blankness.INK_OBSERVED,
            "CURRENCY_SHAPED_OCR_PRESENT",
            details,
        )

    # Live ROI analysis when pixels are available.
    if roi_image is not None:
        try:
            from PIL import Image

            image = roi_image if isinstance(roi_image, Image.Image) else Image.open(roi_image)
            evidence = analyze_roi(
                image,
                field_optional=True,
                geometry_valid=region is not None,
                ocr_empty=parse_currency(box28_amount) is None and not currency,
                field_applicable=True,
            )
            details["image_evidence"] = evidence.to_dict()
            if evidence.disposition == InkDisposition.BLANK_CONFIRMED:
                return Box28BlanknessDecision(
                    Box28Blankness.CONFIRMED_BLANK,
                    "ROI_INK_ANALYSIS_BLANK",
                    details,
                )
            if evidence.disposition == InkDisposition.INK_PRESENT_UNREADABLE:
                return Box28BlanknessDecision(
                    Box28Blankness.INK_PRESENT_UNREADABLE,
                    "ROI_INK_PRESENT_UNREADABLE",
                    details,
                )
            if evidence.disposition in {
                InkDisposition.ROI_MISALIGNED,
                InkDisposition.PIXELS_MISSING,
            }:
                return Box28BlanknessDecision(
                    Box28Blankness.ROI_UNUSABLE,
                    evidence.disposition.value,
                    details,
                )
            if evidence.disposition == InkDisposition.INK_OBSERVED:
                return Box28BlanknessDecision(
                    Box28Blankness.INK_OBSERVED,
                    "ROI_INK_OBSERVED",
                    details,
                )
        except Exception as exc:  # noqa: BLE001
            details["roi_analysis_error"] = type(exc).__name__

    # 2) Persisted image-evidence from OCR / inventory.
    stored = _image_evidence_dict(field_payload, observation)
    if stored is not None:
        details["stored_image_evidence"] = {
            k: stored.get(k)
            for k in (
                "disposition",
                "ink_density",
                "connected_components",
                "blank_probability",
                "reasons",
            )
        }
        disposition = str(stored.get("disposition") or "").upper()
        if disposition in {"BLANK_CONFIRMED", "CONFIRMED_BLANK"}:
            return Box28BlanknessDecision(
                Box28Blankness.CONFIRMED_BLANK,
                "STORED_IMAGE_EVIDENCE_BLANK",
                details,
            )
        if disposition in {"INK_PRESENT_UNREADABLE", "INK_OBSERVED"}:
            status = (
                Box28Blankness.INK_PRESENT_UNREADABLE
                if disposition == "INK_PRESENT_UNREADABLE"
                else Box28Blankness.INK_OBSERVED
            )
            return Box28BlanknessDecision(status, "STORED_IMAGE_EVIDENCE", details)
        if disposition in {"ROI_MISALIGNED", "PIXELS_MISSING", "ROI_UNUSABLE"}:
            return Box28BlanknessDecision(
                Box28Blankness.ROI_UNUSABLE,
                "STORED_IMAGE_EVIDENCE_ROI",
                details,
            )

    if region is None:
        return Box28BlanknessDecision(
            Box28Blankness.ROI_UNUSABLE,
            "BOX28_ROI_MISSING",
            details,
        )

    # OCR-empty without ink analysis stays unclassified — do not derive.
    return Box28BlanknessDecision(
        Box28Blankness.UNCLASSIFIED,
        "OCR_EMPTY_WITHOUT_INK_ANALYSIS",
        details,
    )
