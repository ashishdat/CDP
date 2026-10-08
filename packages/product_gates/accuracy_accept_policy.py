"""Fail-closed accept policy for product FA=0 (going-forward).

Reject AUTO on critical fields when the selected value is a known
placeholder / form-junk pattern. HITL is the correct outcome — not a
failed accuracy event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


# Word-bounded FILL IN — bare FILL\s*IN falsely matched surnames like FILLINGIM.
_PLACEHOLDER_NAME = re.compile(
    r"(LAST\s*NAME|FIRST\s*NAME|LAS[RT]?NANE|PNSTNANE|PNSRNANNE|"
    r"LOOTAITT|SNASLLAST|\bFILL\s*IN\b|PATIENT\s*NAME|INSURED\s*NAME|"
    r"SPONSOR.?S?\s*SSN|SOCIAL\s*SECURITY)",
    re.IGNORECASE,
)
# OCR often reads I.D. as 1.D / L.D; keep the full Box-1a header phrase.
_FORM_LABEL_ID = re.compile(
    r"(INSURED.?S?.?[I1L]\.?D|"
    r"FOR\s*PROGRAM|"
    r"ITEM\s*1|"
    r"1A\.|"
    r"[I1L]\.?D\.?\s*,?\s*NUMBER|"
    r"NUMBER\s*\()",
    re.IGNORECASE,
)
_ALL_ZEROS_ID = re.compile(r"^0+$")
# Leading-zero ISO years (``0195-09-03``) — never AUTO.
_LEADING_ZERO_ISO_YEAR = re.compile(
    r"^0\d{3}[-/]\d{1,2}[-/]\d{1,2}$"
)
_SAME = re.compile(r"^SAME\d{0,2}$", re.IGNORECASE)


@dataclass(frozen=True)
class AcceptVerdict:
    allow_auto: bool
    reason_codes: tuple[str, ...]

    @property
    def block_stp(self) -> bool:
        return not self.allow_auto


def _compact_name(value: str) -> str:
    return re.sub(r"[^A-Za-z]", "", value or "").upper()


def evaluate_insured_name_accept(
    value: str | None,
    *,
    patient_name: str | None = None,
    relationship: str | None = None,
) -> AcceptVerdict:
    text = (value or "").strip()
    if not text:
        return AcceptVerdict(False, ("EMPTY_INSURED_NAME",))
    if _PLACEHOLDER_NAME.search(text):
        return AcceptVerdict(False, ("PLACEHOLDER_INSURED_NAME",))
    compact_alnum = re.sub(r"[^A-Z0-9]", "", text.upper())
    if _SAME.fullmatch(compact_alnum):
        # Literal SAME must be resolved to patient before AUTO.
        return AcceptVerdict(False, ("UNRESOLVED_SAME_INSURED_NAME",))
    # Single token when patient is multi-token Self → incomplete Box4.
    rel = (relationship or "").strip().casefold()
    patient_tokens = [t for t in re.split(r"[^A-Za-z]+", patient_name or "") if t]
    insured_tokens = [t for t in re.split(r"[^A-Za-z]+", text) if t]
    if (
        rel in {"", "self", "1", "01"}
        and len(patient_tokens) >= 2
        and len(insured_tokens) == 1
        and len(insured_tokens[0]) <= 12
    ):
        return AcceptVerdict(False, ("TRUNCATED_INSURED_NAME_VS_PATIENT",))
    return AcceptVerdict(True, ())


def evaluate_insured_id_accept(value: str | None) -> AcceptVerdict:
    text = (value or "").strip()
    if not text:
        return AcceptVerdict(False, ("EMPTY_INSURED_ID",))
    if _FORM_LABEL_ID.search(text):
        return AcceptVerdict(False, ("FORM_LABEL_INSURED_ID",))
    compact = re.sub(r"[^A-Za-z0-9]", "", text)
    if compact and _ALL_ZEROS_ID.fullmatch(compact):
        return AcceptVerdict(False, ("ALL_ZEROS_INSURED_ID",))
    if re.search(r"[\$\(\)]", text) and not re.fullmatch(r"[A-Za-z0-9\-\s]+", text):
        return AcceptVerdict(False, ("JUNK_INSURED_ID",))
    return AcceptVerdict(True, ())


def evaluate_patient_dob_accept(value: str | None) -> AcceptVerdict:
    """Reject leading-zero / sub-1880 year shells (``0195-09-03``) — not AUTO.

    Do **not** treat MMDDYYYY with month ``0X`` (``08/16/1993`` → ``08161993``)
    as junk — that falsely stripped unstructured REG DOBs into HITL.
    """
    text = (value or "").strip()
    if not text:
        return AcceptVerdict(False, ("EMPTY_PATIENT_DOB",))
    compact = text.replace(" ", "")
    if _LEADING_ZERO_ISO_YEAR.fullmatch(compact):
        return AcceptVerdict(False, ("JUNK_DOB_YEAR",))
    # Sparse OCR junk like ``1 1 1`` / ``1/1/1``.
    digits = re.sub(r"\D", "", text)
    if 0 < len(digits) <= 3:
        return AcceptVerdict(False, ("JUNK_DOB_YEAR",))
    if len(digits) == 8 and digits[0] == "0":
        # 0YYYMMDD glue (01950903) is junk. MMDDYYYY with month 01-09
        # (08161993 = 08/16/1993) must still AUTO when the year is plausible.
        mmddyyyy_year = int(digits[4:8])
        yyyymmdd_year = int(digits[0:4])
        if 1880 <= mmddyyyy_year <= 2100:
            return AcceptVerdict(True, ())
        if yyyymmdd_year < 1000:
            return AcceptVerdict(False, ("JUNK_DOB_YEAR",))
    return AcceptVerdict(True, ())


def evaluate_critical_accept(
    field_name: str,
    value: str | None,
    *,
    patient_name: str | None = None,
    relationship: str | None = None,
) -> AcceptVerdict:
    key = (field_name or "").casefold()
    if key == "insured_name":
        return evaluate_insured_name_accept(
            value, patient_name=patient_name, relationship=relationship
        )
    if key in {"insured_id_number", "member_id"}:
        return evaluate_insured_id_accept(value)
    if key in {"patient_dob", "date_of_birth"}:
        return evaluate_patient_dob_accept(value)
    if not (value or "").strip():
        return AcceptVerdict(False, (f"EMPTY_{key.upper()}",))
    return AcceptVerdict(True, ())


def blocking_reason_codes(
    fields: dict[str, str | None],
    *,
    patient_name: str | None = None,
    relationship: str | None = None,
) -> tuple[str, ...]:
    """Return reason codes that must keep the claim in HITL."""
    codes: list[str] = []
    patient = patient_name or fields.get("patient_name")
    for name, value in fields.items():
        verdict = evaluate_critical_accept(
            name,
            value,
            patient_name=patient,
            relationship=relationship,
        )
        if not verdict.allow_auto:
            codes.extend(verdict.reason_codes)
    return tuple(dict.fromkeys(codes))


def filter_auto_fields(
    fields: dict[str, str],
    *,
    patient_name: str | None = None,
    relationship: str | None = None,
) -> tuple[dict[str, str], Sequence[str]]:
    """Drop fields that fail the accept policy; return kept + block reasons."""
    kept: dict[str, str] = {}
    blocked: list[str] = []
    patient = patient_name or fields.get("patient_name")
    for name, value in fields.items():
        verdict = evaluate_critical_accept(
            name,
            value,
            patient_name=patient,
            relationship=relationship,
        )
        if verdict.allow_auto:
            kept[name] = value
        else:
            blocked.extend(verdict.reason_codes)
    return kept, tuple(dict.fromkeys(blocked))
