"""Classify Box 28 ROI blankness — OCR-empty alone is never confirmed blank."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from packages.claim_evidence.line_sum_authority import parse_currency
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
        if parse_currency(text) is not None:
            found.append(str(text))
    for cand in field_payload.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        text = cand.get("value") or cand.get("raw_value")
        if parse_currency(text) is not None:
            found.append(str(text))
    return found


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
    if parse_currency(box28_amount) is not None:
        currency.append(str(box28_amount))
    details["currency_shaped_candidates"] = currency[:8]

    # Currency-shaped OCR means ink was observed — never confirmed blank.
    if currency:
        return Box28BlanknessDecision(
            Box28Blankness.INK_OBSERVED
            if parse_currency(box28_amount) is not None
            else Box28Blankness.INK_PRESENT_UNREADABLE,
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
