"""Deterministic primary/challenger adjudication with fail-closed semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from packages.deterministic_evidence.service import DeterministicEvidenceService
from packages.evidence.normalization import normalize_agreement_value
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group


@dataclass(frozen=True)
class ChallengerAdjudication:
    action: Literal["KEEP_PRIMARY", "USE_CHALLENGER", "HITL"]
    agreement_status: Literal["AGREE", "DISAGREE", "NO_CANDIDATE"]
    reason: str
    primary_valid: bool
    challenger_valid: bool
    evidence_independent: bool


def adjudicate_candidates(
    *,
    field_name: str,
    primary: OCRCandidate | None,
    challenger: OCRCandidate | None,
    crop_safety_status: str,
    deterministic: DeterministicEvidenceService | None = None,
) -> ChallengerAdjudication:
    """Adjudicate without confidence thresholds, LLMs, or acceptance authority."""

    service = deterministic or DeterministicEvidenceService()
    primary_result = service.evaluate(field_name, primary.value if primary else None)
    challenger_result = service.evaluate(field_name, challenger.value if challenger else None)
    if crop_safety_status != "CROP_SAFE":
        return ChallengerAdjudication(
            "HITL", "NO_CANDIDATE" if challenger is None else "DISAGREE",
            "LOCALIZATION_NOT_CROP_SAFE", primary_result.passed,
            challenger_result.passed, False,
        )
    if challenger is None or not challenger.value:
        return ChallengerAdjudication(
            "KEEP_PRIMARY", "NO_CANDIDATE", "CHALLENGER_EMPTY",
            primary_result.passed, False, False,
        )
    independent = (
        primary is not None
        and independence_group(primary.engine) != independence_group(challenger.engine)
        and primary.provenance is not None
        and challenger.provenance is not None
        and primary.bounding_box.normalized() == challenger.bounding_box.normalized()
        and primary.provenance.invocation_id != challenger.provenance.invocation_id
    )
    agrees = (
        primary is not None
        and normalize_agreement_value(field_name, primary.value)
        == normalize_agreement_value(field_name, challenger.value)
    )
    if agrees:
        return ChallengerAdjudication(
            "KEEP_PRIMARY", "AGREE", "INDEPENDENT_ENGINE_AGREEMENT"
            if independent else "AGREEMENT_NOT_INDEPENDENT",
            primary_result.passed, challenger_result.passed, independent,
        )
    if primary_result.passed and challenger_result.passed:
        return ChallengerAdjudication(
            "HITL", "DISAGREE", "INDEPENDENT_VALID_CANDIDATES_DISAGREE",
            True, True, independent,
        )
    if challenger_result.passed and not primary_result.passed and independent:
        return ChallengerAdjudication(
            "USE_CHALLENGER", "DISAGREE", "VALID_INDEPENDENT_CHALLENGER_REPLACES_INVALID_PRIMARY",
            False, True, True,
        )
    return ChallengerAdjudication(
        "HITL", "DISAGREE", "CHALLENGER_ACCEPTANCE_GATES_FAILED",
        primary_result.passed, challenger_result.passed, independent,
    )
