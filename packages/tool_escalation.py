"""Unified residual-tool escalation planner (off the cheap common path).

Maps honest HITL gap classes onto the production stack:

  OpenCV SIFT/FLANN/RANSAC → RapidOCR → Paddle/Tesseract selective
    → Pydantic validators → (gated) Docling / Azure gpt-4o / Textract
    → React field-level HITL

Cloud / Docling never run on the common path. Azure stays review-only until
an untouched holdout promotes a route.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml

from packages.docling_policy import DoclingRouteInput, should_run_docling


class EscalationTool(StrEnum):
    DOCLING = "docling"
    AZURE_GPT4O = "azure_gpt4o"
    TEXTRACT_DETECT_DOCUMENT_TEXT = "aws_textract_detect_document_text"
    REACT_FIELD_HITL = "react_field_hitl"
    OPENCV_REGISTRATION_HITL = "opencv_registration_hitl"
    NONE = "none"


@dataclass(frozen=True)
class EscalationDecision:
    tool: EscalationTool
    reason: str
    review_only: bool
    blocks_common_path: bool = True


@lru_cache(maxsize=4)
def load_secondary_policy(path: str | Path = "config/secondary_ocr_policy_v1.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def plan_field_escalation(
    *,
    gap_class: str,
    field_name: str,
    regional_ocr_attempted: bool = True,
    service_line_rows_missing: bool = False,
    empty_financial_ink: bool = False,
    table_detected: bool = False,
    template_extraction_failed: bool = False,
    document_category: str | None = None,
    policy: dict | None = None,
) -> EscalationDecision:
    """Pick the next gated tool after local Rapid→Paddle/Tesseract exhaustion."""
    policy = policy or load_secondary_policy()
    gap = (gap_class or "").upper()
    field = (field_name or "").casefold()

    if gap in {"REGISTRATION_HITL", "REGISTRATION_FAILED"}:
        return EscalationDecision(
            EscalationTool.OPENCV_REGISTRATION_HITL,
            "OpenCV SIFT/FLANN/RANSAC recovery exhausted — fail-closed Track A",
            review_only=True,
        )

    if gap == "EMPTY_FINANCIAL_INK" or (
        field in {"total_charge", "total_charges", "charges"} and empty_financial_ink
    ):
        docling_ok = should_run_docling(
            DoclingRouteInput(
                table_detected=table_detected or True,
                template_extraction_failed=template_extraction_failed or True,
                table_heavy_unstructured=False,
                regional_ocr_attempted=regional_ocr_attempted,
                empty_financial_ink=True,
                service_line_rows_missing=service_line_rows_missing,
                document_category=document_category,
            )
        )
        if docling_ok and regional_ocr_attempted:
            return EscalationDecision(
                EscalationTool.DOCLING,
                "Difficult table / empty finance after regional OCR",
                review_only=False,
            )
        if policy.get("textract_enabled") and regional_ocr_attempted:
            return EscalationDecision(
                EscalationTool.TEXTRACT_DETECT_DOCUMENT_TEXT,
                "Local OCR exhausted and charge blocks STP",
                review_only=False,
            )
        return EscalationDecision(
            EscalationTool.REACT_FIELD_HITL,
            "Empty financial ink — field-scoped human entry",
            review_only=True,
        )

    if gap in {"HANDWRITING_UNREADABLE", "AMBIGUOUS_DIGIT_FRAGMENTS"} or field in {
        "patient_dob",
        "date_of_birth",
    }:
        if policy.get("azure_ai_cascade_enabled"):
            return EscalationDecision(
                EscalationTool.AZURE_GPT4O,
                "Handwriting / orientation residual — Azure gpt-4o crop cascade",
                review_only=bool(policy.get("azure_review_only_until_promoted", True)),
            )
        return EscalationDecision(
            EscalationTool.REACT_FIELD_HITL,
            "Handwriting residual without Azure — React field HITL",
            review_only=True,
        )

    if gap == "CALIBRATION_HITL":
        return EscalationDecision(
            EscalationTool.REACT_FIELD_HITL,
            "Format-valid but uncalibrated — corroborate or human confirm",
            review_only=True,
        )

    return EscalationDecision(
        EscalationTool.REACT_FIELD_HITL,
        f"Residual gap {gap or 'UNKNOWN'} → React field HITL",
        review_only=True,
    )
