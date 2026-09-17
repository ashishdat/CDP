"""Crop-scoped Azure Document Intelligence for DOB-only residuals.

Runs only after local Rapid→Paddle/Tesseract exhaustion on handwriting /
ambiguous-digit DOB gaps. Never on the common path. Results stay
SHADOW_REVIEW_ONLY until secondary policy promotes the route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.tool_escalation import EscalationTool, plan_field_escalation


_DOB_FIELDS = frozenset({"patient_dob", "date_of_birth"})
_HANDWRITING_GAPS = frozenset({"HANDWRITING_UNREADABLE", "AMBIGUOUS_DIGIT_FRAGMENTS"})


@dataclass(frozen=True)
class DobAzureDiResidualResult:
    attempted: bool
    configured: bool
    review_only: bool
    value: str | None
    raw_value: str | None
    date_shaped: bool
    reason: str
    engine: str = "azure_document_intelligence_read"
    validation_results: tuple[str, ...] = ()


class DobCropRecognizer(Protocol):
    def recognize_crop(
        self, crop: Image.Image, field_name: str
    ) -> DobAzureDiResidualResult: ...


def is_dob_handwriting_residual(
    *,
    field_name: str,
    gap_class: str | None,
    local_accepted: bool,
) -> bool:
    if local_accepted:
        return False
    if (field_name or "").casefold() not in _DOB_FIELDS:
        return False
    gap = (gap_class or "").upper()
    return gap in _HANDWRITING_GAPS or gap == ""


def _crop_image(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = max(x0 + 1, int(x1)), max(y0 + 1, int(y1))
    return image.crop((x0, y0, x1, y1))


def _normalize_dob_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned or None


def _recognize_with_azure_read_engine(
    read_engine: Any,
    crop: Image.Image,
    field_name: str,
    *,
    review_only: bool,
) -> DobAzureDiResidualResult:
    from packages.domain.common import BoundingBox
    from packages.domain.enums import ClaimFormType, FieldCriticality
    from packages.ocr.contracts import OCRRequest

    box = BoundingBox(
        x0=0.0,
        y0=0.0,
        x1=float(crop.width),
        y1=float(crop.height),
        image_width=crop.width,
        image_height=crop.height,
    )
    request = OCRRequest(
        document_id="dob-azure-di-residual",
        page_number=1,
        field_name=field_name,
        field_type="date",
        form_type=ClaimFormType.CMS1500,
        image=crop,
        bounding_box=box,
        criticality=FieldCriticality.CRITICAL,
        scope="FIELD_CROP",
    )
    try:
        candidates = read_engine.recognize(request)
    except Exception as exc:  # noqa: BLE001
        try:
            from packages.recovery.azure_di_meter import record_azure_di_call

            record_azure_di_call(
                kind="dob_crop",
                field_name=field_name,
                ok=False,
                detail=type(exc).__name__,
            )
        except Exception:  # noqa: BLE001
            pass
        return DobAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason=f"AZURE_DI_ERROR:{type(exc).__name__}",
        )
    try:
        from packages.recovery.azure_di_meter import record_azure_di_call

        record_azure_di_call(
            kind="dob_crop",
            field_name=field_name,
            ok=bool(candidates),
            detail="ok" if candidates else "empty",
        )
    except Exception:  # noqa: BLE001
        pass
    if not candidates:
        return DobAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason="AZURE_DI_EMPTY",
        )
    lead = candidates[0]
    raw = _normalize_dob_text(getattr(lead, "raw_value", None) or getattr(lead, "value", None))
    value = _normalize_dob_text(getattr(lead, "value", None) or raw)
    shaped = bool(value) and semantic_accept(field_name, value)[0]
    validations = tuple(getattr(lead, "validation_results", ()) or ())
    if "SHADOW_REVIEW_ONLY" not in validations:
        validations = (*validations, "SHADOW_REVIEW_ONLY")
    return DobAzureDiResidualResult(
        attempted=True,
        configured=True,
        review_only=review_only,
        value=value,
        raw_value=raw,
        date_shaped=shaped,
        reason=(
            "AZURE_DI_DATE_SHAPED_REVIEW_ONLY"
            if shaped and review_only
            else "AZURE_DI_DATE_SHAPED"
            if shaped
            else "AZURE_DI_UNSHAPED"
        ),
        validation_results=validations,
    )


def run_dob_azure_di_residual(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str = "patient_dob",
    gap_class: str | None = "HANDWRITING_UNREADABLE",
    local_accepted: bool = False,
    trocr_attempted: bool = True,
    azure_di_attempted: bool = False,
    settings: Any | None = None,
    engine: Any | None = None,
) -> DobAzureDiResidualResult:
    """Invoke crop-scoped Azure DI Read when the planner selects it for DOB.

    Default ``trocr_attempted=True`` so Azure DI is the fallback after local
    TrOCR (preferred) rather than being skipped by the planner.
    """
    if not is_dob_handwriting_residual(
        field_name=field_name,
        gap_class=gap_class,
        local_accepted=local_accepted,
    ):
        return DobAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason="NOT_DOB_HANDWRITING_RESIDUAL",
        )

    decision = plan_field_escalation(
        gap_class=gap_class or "HANDWRITING_UNREADABLE",
        field_name=field_name,
        trocr_attempted=trocr_attempted,
        azure_di_attempted=azure_di_attempted,
    )
    if decision.tool != EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ:
        return DobAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=decision.review_only,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason=f"PLANNER_SKIPPED:{decision.tool.value}",
        )

    crop = _crop_image(image, bbox)
    try:
        if engine is not None:
            if hasattr(engine, "recognize_crop"):
                return engine.recognize_crop(crop, field_name)
            return _recognize_with_azure_read_engine(
                engine, crop, field_name, review_only=decision.review_only
            )

        try:
            from packages.settings import get_settings
            from workers.cascade.azure_di_factory import (
                AzureDocumentIntelligenceConfigurationError,
                azure_document_intelligence_configured,
                build_azure_read_engine,
            )
        except Exception as exc:  # noqa: BLE001
            return DobAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason=f"IMPORT_ERROR:{type(exc).__name__}",
            )

        cfg = settings or get_settings()
        if not azure_document_intelligence_configured(cfg):
            return DobAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason="AZURE_DI_NOT_CONFIGURED",
            )
        try:
            read_engine = build_azure_read_engine(cfg)
        except AzureDocumentIntelligenceConfigurationError as exc:
            return DobAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason=f"AZURE_DI_CONFIG_ERROR:{exc}",
            )
        return _recognize_with_azure_read_engine(
            read_engine, crop, field_name, review_only=decision.review_only
        )
    finally:
        crop.close()


def residual_candidate_dict(result: DobAzureDiResidualResult) -> dict[str, Any] | None:
    """Serialize a DI residual into an OCR-candidates-compatible shadow row."""
    if not result.attempted or not result.value:
        return None
    return {
        "value": result.value,
        "raw_value": result.raw_value or result.value,
        "engine": result.engine,
        "model_name": "prebuilt-read",
        "model_version": "unknown",
        "preprocessing_variant": "dob_azure_di_crop_residual",
        "raw_confidence": None,
        "calibrated_confidence": None,
        "reason_code": result.reason,
        "validation_results": list(result.validation_results),
        "shadow_review_only": result.review_only,
    }


def maybe_attach_dob_azure_di_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    gap_class: str | None,
    settings: Any | None = None,
    engine: Any | None = None,
    trocr_attempted: bool = True,
) -> dict[str, Any]:
    """Return an updated field row with optional Azure DI shadow candidate."""
    name = str(field_row.get("field") or "")
    cascade = field_row.get("cascade") or {}
    local_accepted = bool(cascade.get("accepted"))
    bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return dict(field_row)
    result = run_dob_azure_di_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        gap_class=gap_class,
        local_accepted=local_accepted,
        trocr_attempted=trocr_attempted,
        settings=settings,
        engine=engine,
    )
    updated = dict(field_row)
    updated["azure_di_residual"] = {
        "attempted": result.attempted,
        "configured": result.configured,
        "review_only": result.review_only,
        "date_shaped": result.date_shaped,
        "reason": result.reason,
        "value": result.value,
    }
    candidate = residual_candidate_dict(result)
    if candidate is not None:
        candidates = list(updated.get("candidates") or [])
        candidates.append(candidate)
        updated["candidates"] = candidates
    return updated
