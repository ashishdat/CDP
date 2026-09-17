"""Unified residual-tool escalation planner (off the cheap common path).

Maps honest HITL gap classes onto the production stack:

  OpenCV SIFT/FLANN/RANSAC → RapidOCR → Paddle/Tesseract selective
    → Pydantic validators
    → (gated) TrOCR → Docling / Azure Document Intelligence Read / Azure gpt-4o / Textract
    → React field-level HITL

Cloud / Docling never run on the common path. Local TrOCR is preferred for
DOB handwriting residuals; Azure DI and gpt-4o stay review-only until an
untouched holdout promotes a route.
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
    TROCR = "trocr"
    DOCUMENT_QUAD_RECOVERY = "document_quad_recovery"
    LEARNED_MATCHER = "superpoint_lightglue"
    AZURE_DOCUMENT_INTELLIGENCE_READ = "azure_document_intelligence_read"
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
    trocr_attempted: bool = False,
    azure_di_attempted: bool = False,
    document_quad_attempted: bool = False,
    learned_matcher_attempted: bool = False,
    azure_di_corners_attempted: bool = False,
    policy: dict | None = None,
) -> EscalationDecision:
    """Pick the next gated tool after local Rapid→Paddle/Tesseract exhaustion."""
    policy = policy or load_secondary_policy()
    gap = (gap_class or "").upper()
    field = (field_name or "").casefold()
    trocr_enabled = bool(policy.get("trocr_enabled", True))
    trocr_review_only = bool(policy.get("trocr_review_only_until_promoted", False))
    di_enabled = bool(policy.get("azure_document_intelligence_enabled", False))
    di_review_only = bool(
        policy.get("azure_document_intelligence_review_only_until_promoted", True)
    )

    if gap in {"REGISTRATION_HITL", "REGISTRATION_FAILED", "CATASTROPHIC_TRANSFORM"}:
        # Catastrophic warps: quad → SuperPoint/LightGlue → Azure DI corners → HITL.
        # Azure DI (configured) replaces gpt-4o for page-corner recovery.
        quad_enabled = bool(policy.get("document_quad_recovery_enabled", True))
        if quad_enabled and not document_quad_attempted:
            return EscalationDecision(
                EscalationTool.DOCUMENT_QUAD_RECOVERY,
                "Catastrophic warp — document-quad crop then re-SIFT",
                review_only=False,
            )
        learned_enabled = bool(policy.get("learned_matcher_enabled", True))
        if learned_enabled and not learned_matcher_attempted:
            return EscalationDecision(
                EscalationTool.LEARNED_MATCHER,
                "Catastrophic warp — SuperPoint+LightGlue then same Acceptance gates",
                review_only=False,
            )
        if di_enabled and not azure_di_corners_attempted:
            corners_on = bool(policy.get("registration_azure_di_corners_enabled", False))
            if corners_on:
                return EscalationDecision(
                    EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ,
                    "Catastrophic warp — Azure DI ink-polygon page corners",
                    review_only=False,
                )
        return EscalationDecision(
            EscalationTool.OPENCV_REGISTRATION_HITL,
            "OpenCV SIFT/FLANN/RANSAC + LightGlue + Azure DI exhausted — fail-closed Track A",
            review_only=True,
        )

    if gap in {
        "CHARGE_LOCAL_EXHAUSTED",
        "CHARGE_DIGIT_CONFLICT",
        "AMBIGUOUS_CHARGE_DIGITS",
    } or (
        field in {"total_charge", "total_charges", "charges", "charge_amount"}
        and gap == "AMBIGUOUS_DIGIT_FRAGMENTS"
    ):
        # Service-line / box-28 crop residual after local fast+paddle/rapid.
        # Prefer Azure DI crop (cheap) over Docling/full-page; never common path.
        charge_di_on = bool(policy.get("azure_document_intelligence_enabled", False))
        # Env can disable charge crops independently of DOB/corners.
        import os

        env_off = (os.environ.get("CDP_AZURE_DI_CHARGE_RESIDUAL") or "1").strip().casefold() in {
            "0",
            "false",
            "no",
            "off",
        }
        if charge_di_on and not env_off and not azure_di_attempted:
            return EscalationDecision(
                EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ,
                "Charge cell residual — Azure DI prebuilt-read crop after local verify",
                review_only=di_review_only,
            )
        return EscalationDecision(
            EscalationTool.REACT_FIELD_HITL,
            "Charge residual without Azure DI — field-scoped human entry",
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
        if di_enabled and regional_ocr_attempted and not azure_di_attempted:
            return EscalationDecision(
                EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ,
                "Empty finance — Azure Document Intelligence prebuilt-read",
                review_only=di_review_only,
            )
        if policy.get("textract_enabled") and regional_ocr_attempted:
            return EscalationDecision(
                EscalationTool.TEXTRACT_DETECT_DOCUMENT_TEXT,
                "Local OCR + Azure DI exhausted and charge blocks STP",
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
        # Prefer local TrOCR over Azure DI for DOB handwriting residuals.
        if trocr_enabled and not trocr_attempted:
            return EscalationDecision(
                EscalationTool.TROCR,
                "Handwriting residual — local TrOCR crop read",
                review_only=trocr_review_only,
            )
        if di_enabled and not azure_di_attempted:
            return EscalationDecision(
                EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ,
                "Handwriting residual — Azure Document Intelligence prebuilt-read",
                review_only=di_review_only,
            )
        if policy.get("azure_ai_cascade_enabled"):
            return EscalationDecision(
                EscalationTool.AZURE_GPT4O,
                "Handwriting / orientation residual — Azure gpt-4o crop cascade",
                review_only=bool(policy.get("azure_review_only_until_promoted", True)),
            )
        return EscalationDecision(
            EscalationTool.REACT_FIELD_HITL,
            "Handwriting residual without TrOCR/Azure — React field HITL",
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
