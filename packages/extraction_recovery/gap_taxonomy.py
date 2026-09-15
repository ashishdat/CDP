"""Honest residual HITL gap classification (no auto-accept side effects)."""

from __future__ import annotations

from dataclasses import dataclass

from .strategy import load_cascade_strategy


@dataclass(frozen=True)
class GapClassification:
    gap_class: str
    action: str
    field_name: str
    evidence: str


def classify_field_gap(
    field_name: str,
    *,
    observed_text: str = "",
    accepted: bool = False,
    service_line_charges: int = 0,
) -> GapClassification | None:
    """Classify why a critical field remains HITL after cascade exhaustion."""
    if accepted:
        return None
    name = (field_name or "").casefold()
    text = (observed_text or "").strip()
    strategy = load_cascade_strategy()
    catalog = strategy.gap_classes

    def _pack(gap_class: str, evidence: str) -> GapClassification:
        meta = catalog.get(gap_class) or {}
        return GapClassification(
            gap_class=gap_class,
            action=str(meta.get("action") or "Keep HITL"),
            field_name=field_name,
            evidence=evidence,
        )

    if name in {"patient_dob", "date_of_birth"}:
        if not text:
            return _pack("HANDWRITING_UNREADABLE", "no DOB OCR ink in crop ladder / cells")
        digits = sum(ch.isdigit() for ch in text)
        letters = sum(ch.isalpha() for ch in text)
        if letters and digits < 4:
            return _pack(
                "HANDWRITING_UNREADABLE",
                f"header/handwriting OCR only ({text!r})",
            )
        return _pack(
            "AMBIGUOUS_DIGIT_FRAGMENTS",
            f"digit fragments present but not calendar-unique ({text!r})",
        )

    if name in {"total_charge", "total_charges", "charges"}:
        if service_line_charges > 0:
            return _pack(
                "EMPTY_FINANCIAL_INK",
                f"box-28 empty/invalid; {service_line_charges} observed line charge(s) available for sum",
            )
        if text and any(tok in text.upper() for tok in ("NPI", "NATIONAL")):
            return _pack("NPI_CONTAMINATED_CHARGE", f"charge crop contaminated ({text!r})")
        return _pack("EMPTY_FINANCIAL_INK", "no box-28 ink and no observed line charges")

    return _pack("HANDWRITING_UNREADABLE", f"unresolved field ink ({text!r})")
