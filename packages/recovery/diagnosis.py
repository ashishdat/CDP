from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class Cause(StrEnum):
    POOR_SCAN = "POOR_SCAN"
    WRONG_TEMPLATE = "WRONG_TEMPLATE"
    TEMPLATE_EVOLUTION = "TEMPLATE_EVOLUTION"
    MISSING_ASSET = "MISSING_ASSET"
    REGISTRATION_FAILURE = "REGISTRATION_FAILURE"
    OCR_FAILURE = "OCR_FAILURE"
    UNKNOWN_DOCUMENT = "UNKNOWN_DOCUMENT"
    UNSUPPORTED_FORM = "UNSUPPORTED_FORM"
    CONTRACT_FAILURE = "CONTRACT_FAILURE"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class Diagnosis:
    """A routing diagnosis, not a claim that a physical cause is proven."""

    primary_cause: Cause
    confidence: str
    evidence: tuple[str, ...] = ()
    contributors: tuple[Cause, ...] = ()
    reason: str = ""


def diagnose(
    failure_reasons: Iterable[str],
    *,
    asset_missing: bool = False,
    document_unknown: bool = False,
    unsupported_form: bool = False,
    contract_failure: bool = False,
    source_quality_failure: bool = False,
    template_incompatible: bool = False,
    ocr_attempted: bool = False,
    evidence: Iterable[str] = (),
) -> Diagnosis:
    """Classify a failure without retrying or guessing.

    Only explicit, high-signal facts receive a deterministic cause. Generic
    stage/safety reasons remain UNDETERMINED because a failed gate is a
    mechanism, not proof of its physical root cause.
    """
    reasons = tuple(str(item) for item in failure_reasons)
    extra = tuple(str(item) for item in evidence)
    if contract_failure:
        return Diagnosis(Cause.CONTRACT_FAILURE, "HIGH", extra + reasons, reason="Artifact contract failure")
    if asset_missing:
        return Diagnosis(Cause.MISSING_ASSET, "HIGH", extra + reasons, reason="Required asset is unavailable")
    if unsupported_form:
        return Diagnosis(Cause.UNSUPPORTED_FORM, "HIGH", extra + reasons, reason="Form is outside qualified scope")
    if document_unknown:
        return Diagnosis(Cause.UNKNOWN_DOCUMENT, "MEDIUM", extra + reasons, reason="Document identity is unresolved")
    if source_quality_failure:
        return Diagnosis(Cause.POOR_SCAN, "MEDIUM", extra + reasons, reason="Source quality defect is explicitly recorded")
    if template_incompatible:
        return Diagnosis(Cause.WRONG_TEMPLATE, "MEDIUM", extra + reasons, reason="Template incompatibility is explicitly established")
    if ocr_attempted and any("regional_ocr_empty" in item.casefold() for item in reasons):
        # Empty regional read after a prepared crop is an explicit OCR signal
        # strong enough for one bounded alternate-prep attempt.
        return Diagnosis(
            Cause.OCR_FAILURE,
            "MEDIUM",
            extra + reasons,
            reason="Regional OCR returned empty text after a prepared crop",
        )
    if ocr_attempted and any("ocr" in item.casefold() for item in reasons):
        return Diagnosis(Cause.OCR_FAILURE, "LOW", extra + reasons, reason="OCR failure was observed after valid prerequisites")
    return Diagnosis(
        Cause.UNDETERMINED,
        "INSUFFICIENT_EVIDENCE",
        extra + reasons,
        reason="Recorded failure mechanism does not establish a physical root cause",
    )
