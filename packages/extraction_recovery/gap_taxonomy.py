"""Honest residual HITL gap classification (no auto-accept side effects)."""

from __future__ import annotations

from dataclasses import dataclass

from .strategy import load_cascade_strategy

_E3_PLUMBING_REASONS = frozenset(
    {
        "MISSING_E3_REGISTRATION_EVIDENCE",
        "ACQUIRE_E3",
        "MISSING_E3",
    }
)
_POLICY_GAP_REASONS = frozenset(
    {
        "MISSING_E2_INDEPENDENT_CONFIRMATION",
        "MISSING_E4_DETERMINISTIC_VALIDATION",
        "MISSING_E6_CROSS_FIELD_CONFIRMATION",
        "ACQUIRE_E2",
        "ACQUIRE_E4",
        "ACQUIRE_E6",
        "CHEAPEST_POLICY_COMPLETING_EVIDENCE",
    }
)


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
    reason_codes: list[str] | tuple[str, ...] | None = None,
) -> GapClassification | None:
    """Classify why a critical field remains HITL after cascade exhaustion.

    Plumbing failures (missing E3) must not be labeled as handwriting / empty ink.
    """
    if accepted:
        return None
    name = (field_name or "").casefold()
    text = (observed_text or "").strip()
    reasons = {str(r) for r in (reason_codes or [])}
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

    if reasons & _E3_PLUMBING_REASONS:
        return _pack(
            "EVIDENCE_PLUMBING_GAP",
            f"decision missing E3 registration evidence ({sorted(reasons & _E3_PLUMBING_REASONS)})",
        )

    auth_reasons = {r for r in reasons if r.startswith("CANDIDATE_ENGINE_NOT_AUTHORIZED")}
    if auth_reasons:
        return _pack(
            "EVIDENCE_PLUMBING_GAP",
            f"assembled candidate stripped by route engine authority ({sorted(auth_reasons)})",
        )

    if "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" in reasons and text:
        return _pack(
            "CALIBRATION_HITL",
            f"calendar/format-valid value held for calibrated confidence ({text!r})",
        )

    if text and reasons & _POLICY_GAP_REASONS:
        held = sorted(reasons & _POLICY_GAP_REASONS)
        return _pack(
            "EVIDENCE_POLICY_GAP",
            f"value observed; evidence policy still unsatisfied ({held})",
        )

    # Observed name ink with engine conflict is not "unread handwriting" —
    # local OCR already saw letters; gpt-4o crop is the conflict arbitrator.
    if (
        name in {"patient_name", "insured_name"}
        and text
        and "CONFLICT_MARGIN_TOO_SMALL" in reasons
    ):
        return _pack(
            "NAME_ENGINE_CONFLICT",
            "local OCR engines disagree on observed name ink",
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
        # Prefer reason-code signal when summarize / OCR count drifts — last-20
        # runs mislabeled LINE_SUM as EMPTY_FINANCIAL_INK when lines existed.
        line_sum_reasons = {
            r
            for r in reasons
            if "LINE_TOTALS_UNCORROBORATED" in r
            or r.startswith("LINE_TOTALS_GATE:")
            or r in {"LINE_TOTALS_RECONCILED", "LINE_TOTALS_CORROBORATED"}
        }
        if service_line_charges > 0 or line_sum_reasons:
            n = service_line_charges or (
                1 if any("LINE_TOTALS" in r for r in line_sum_reasons) else 0
            )
            return _pack(
                "LINE_SUM_UNCORROBORATED",
                f"box-28 empty/invalid; {n} observed line charge(s) need dual-engine or gpt-4o corroboration",
            )
        if text and any(tok in text.upper() for tok in ("NPI", "NATIONAL")):
            return _pack("NPI_CONTAMINATED_CHARGE", f"charge crop contaminated ({text!r})")
        return _pack("EMPTY_FINANCIAL_INK", "no box-28 ink and no observed line charges")

    return _pack("HANDWRITING_UNREADABLE", f"unresolved field ink ({text!r})")
