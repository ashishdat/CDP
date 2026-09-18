"""Crop-scoped Azure Document Intelligence for service-line charge residuals.

Runs only after local CHARGE_DIGITS_FAST → paddle/rapid verify still leaves
the cell empty or unresolved. Never on the common path. Full-page Azure DI
corners stay off; this is one cheap charge-cell crop (same pattern as DOB).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span
from packages.tool_escalation import EscalationTool, plan_field_escalation


_CHARGE_FIELDS = frozenset(
    {"charges", "charge_amount", "total_charge", "total_charges", "amount_paid"}
)
_CHARGE_GAPS = frozenset(
    {
        "EMPTY_FINANCIAL_INK",
        "CHARGE_LOCAL_EXHAUSTED",
        "CHARGE_DIGIT_CONFLICT",
        "AMBIGUOUS_DIGIT_FRAGMENTS",
        "AMBIGUOUS_CHARGE_DIGITS",
    }
)


@dataclass(frozen=True)
class ChargeAzureDiResidualResult:
    attempted: bool
    configured: bool
    review_only: bool
    value: str | None
    raw_value: str | None
    currency_shaped: bool
    reason: str
    engine: str = "azure_document_intelligence_read"
    validation_results: tuple[str, ...] = ()


class ChargeCropRecognizer(Protocol):
    def recognize_crop(
        self, crop: Image.Image, field_name: str
    ) -> ChargeAzureDiResidualResult: ...


def _env_on(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def azure_di_charge_residual_enabled() -> bool:
    return _env_on("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")


def azure_di_charge_accept_enabled() -> bool:
    return _env_on("CDP_AZURE_DI_CHARGE_ACCEPT", "1")


def is_charge_local_residual(
    *,
    field_name: str,
    gap_class: str | None,
    local_accepted: bool,
    corroborate: bool = False,
) -> bool:
    # Corroboration path: still run DI after a weak/single-engine local accept.
    if local_accepted and not corroborate:
        return False
    if (field_name or "").casefold() not in _CHARGE_FIELDS:
        return False
    gap = (gap_class or "").upper()
    return gap in _CHARGE_GAPS or gap == "" or corroborate


def _crop_image(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = max(x0 + 1, int(x1)), max(y0 + 1, int(y1))
    return image.crop((x0, y0, x1, y1))


def _normalize_charge_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned or None


def _shape_charge_text(field_name: str, raw: str | None) -> tuple[str | None, bool]:
    """Span-select then semantic-accept so DI noise around an amount can shape."""
    text = _normalize_charge_text(raw)
    if not text:
        return None, False
    # Prefer explicit currency; fall back to digit spans from noisy DI lines.
    span = select_field_span(text, "CURRENCY", field_name)
    selected = _normalize_charge_text(span.selected_text) or text
    if not re.search(r"\d", selected or ""):
        return selected, False
    # Strip label bleed; keep first currency-shaped token.
    m = re.search(
        r"\$?\d{1,3}(?:,\d{3})*\.\d{2}|\$?\d{2,6}(?:\.\d{2})?",
        selected or "",
    )
    if m:
        amount = m.group(0).lstrip("$").replace(",", "")
        if "." not in amount and re.fullmatch(r"\d{2,6}", amount):
            amount = f"{amount}.00"
        selected = amount
    shaped = bool(selected) and semantic_accept(field_name, selected)[0]
    if not shaped and selected and re.fullmatch(r"\d+\.\d{2}", selected):
        shaped = True
    return selected, shaped


def _recognize_with_azure_read_engine(
    read_engine: Any,
    crop: Image.Image,
    field_name: str,
    *,
    review_only: bool,
) -> ChargeAzureDiResidualResult:
    from packages.domain.common import BoundingBox
    from packages.domain.enums import ClaimFormType, FieldCriticality
    from packages.ocr.contracts import OCRRequest

    # Azure DI rejects tiny / blank crops — upscale charge cells like DOB.
    working = crop
    min_side = 64
    min_w, min_h = 160, 64
    ow, oh = working.size
    if ow < min_w or oh < min_h or min(ow, oh) < min_side:
        scale = max(min_w / max(1, ow), min_h / max(1, oh), 1.0)
        nw, nh = max(min_w, int(ow * scale)), max(min_h, int(oh * scale))
        working = working.resize((nw, nh), Image.Resampling.LANCZOS)

    box = BoundingBox(
        x0=0.0,
        y0=0.0,
        x1=float(working.width),
        y1=float(working.height),
        image_width=working.width,
        image_height=working.height,
    )
    request = OCRRequest(
        document_id="charge-azure-di-residual",
        page_number=1,
        field_name=field_name,
        field_type="currency",
        form_type=ClaimFormType.CMS1500,
        image=working,
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
                kind="charge_crop",
                field_name=field_name,
                ok=False,
                detail=type(exc).__name__,
            )
        except Exception:  # noqa: BLE001
            pass
        return ChargeAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason=f"AZURE_DI_ERROR:{type(exc).__name__}",
        )
    try:
        from packages.recovery.azure_di_meter import record_azure_di_call

        record_azure_di_call(
            kind="charge_crop",
            field_name=field_name,
            ok=bool(candidates),
            detail="ok" if candidates else "empty",
        )
    except Exception:  # noqa: BLE001
        pass
    if not candidates:
        return ChargeAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason="AZURE_DI_EMPTY",
        )
    lead = candidates[0]
    raw = _normalize_charge_text(
        getattr(lead, "raw_value", None) or getattr(lead, "value", None)
    )
    value, shaped = _shape_charge_text(field_name, raw)
    validations = tuple(getattr(lead, "validation_results", ()) or ())
    if "SHADOW_REVIEW_ONLY" not in validations:
        validations = (*validations, "SHADOW_REVIEW_ONLY")
    return ChargeAzureDiResidualResult(
        attempted=True,
        configured=True,
        review_only=review_only,
        value=value,
        raw_value=raw,
        currency_shaped=shaped,
        reason=(
            "AZURE_DI_CURRENCY_SHAPED_REVIEW_ONLY"
            if shaped and review_only
            else "AZURE_DI_CURRENCY_SHAPED"
            if shaped
            else "AZURE_DI_UNSHAPED"
        ),
        validation_results=validations,
    )


def run_charge_azure_di_residual(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str = "charges",
    gap_class: str | None = "CHARGE_LOCAL_EXHAUSTED",
    local_accepted: bool = False,
    azure_di_attempted: bool = False,
    settings: Any | None = None,
    engine: Any | None = None,
    corroborate: bool = False,
) -> ChargeAzureDiResidualResult:
    """Invoke crop-scoped Azure DI Read when local charge OCR is exhausted."""
    if not azure_di_charge_residual_enabled():
        return ChargeAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason="AZURE_DI_CHARGE_RESIDUAL_DISABLED",
        )
    if not is_charge_local_residual(
        field_name=field_name,
        gap_class=gap_class,
        local_accepted=local_accepted,
        corroborate=corroborate,
    ):
        return ChargeAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason="NOT_CHARGE_LOCAL_RESIDUAL",
        )

    decision = plan_field_escalation(
        gap_class=gap_class or "CHARGE_LOCAL_EXHAUSTED",
        field_name=field_name,
        regional_ocr_attempted=True,
        empty_financial_ink=True,
        azure_di_attempted=azure_di_attempted,
    )
    if decision.tool != EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ:
        return ChargeAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=decision.review_only,
            value=None,
            raw_value=None,
            currency_shaped=False,
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
            return ChargeAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                currency_shaped=False,
                reason=f"IMPORT_ERROR:{type(exc).__name__}",
            )

        cfg = settings or get_settings()
        if not azure_document_intelligence_configured(cfg):
            return ChargeAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                currency_shaped=False,
                reason="AZURE_DI_NOT_CONFIGURED",
            )
        try:
            read_engine = build_azure_read_engine(cfg)
        except AzureDocumentIntelligenceConfigurationError as exc:
            return ChargeAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                currency_shaped=False,
                reason=f"AZURE_DI_CONFIG_ERROR:{exc}",
            )
        return _recognize_with_azure_read_engine(
            read_engine, crop, field_name, review_only=decision.review_only
        )
    finally:
        crop.close()


def residual_candidate_dict(
    result: ChargeAzureDiResidualResult,
    *,
    bbox: tuple[int, int, int, int] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    if not result.attempted or not result.value:
        return None
    width = int(image_size[0]) if image_size else max(1, int((bbox or (0, 0, 1, 1))[2]))
    height = int(image_size[1]) if image_size else max(1, int((bbox or (0, 0, 1, 1))[3]))
    x0, y0, x1, y1 = bbox or (0, 0, width, height)
    return {
        "value": result.value,
        "raw_value": result.raw_value or result.value,
        "engine": result.engine,
        "model_name": "prebuilt-read",
        "model_version": "unknown",
        "preprocessing_variant": "charge_azure_di_crop_residual",
        "preprocessing_version": "cascade-v12-azure-di",
        "raw_confidence": 0.85,
        "calibrated_confidence": 0.85,
        "reason_code": result.reason,
        "validation_results": list(result.validation_results),
        "shadow_review_only": result.review_only,
        "latency_ms": 0.0,
        "bounding_box": {
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
            "image_width": float(width),
            "image_height": float(height),
        },
    }


def promote_currency_shaped(
    result: ChargeAzureDiResidualResult,
) -> ChargeAzureDiResidualResult:
    """Drop SHADOW_REVIEW_ONLY when currency-shaped accept is enabled."""
    if not (
        azure_di_charge_accept_enabled()
        and result.currency_shaped
        and result.review_only
        and result.value
    ):
        return result
    validations = tuple(
        v for v in result.validation_results if v != "SHADOW_REVIEW_ONLY"
    )
    return ChargeAzureDiResidualResult(
        attempted=result.attempted,
        configured=result.configured,
        review_only=False,
        value=result.value,
        raw_value=result.raw_value,
        currency_shaped=True,
        reason="AZURE_DI_CURRENCY_SHAPED",
        engine=result.engine,
        validation_results=validations or ("AZURE_DI_CHARGE_CROP",),
    )


def maybe_attach_charge_azure_di_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    gap_class: str | None,
    settings: Any | None = None,
    engine: Any | None = None,
    corroborate: bool = False,
) -> dict[str, Any]:
    """Return an updated field row with optional Azure DI charge candidate."""
    name = str(field_row.get("field") or "charges")
    cascade = field_row.get("cascade") or {}
    local_accepted = bool(cascade.get("accepted"))
    bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return dict(field_row)
    do_corroborate = corroborate or (
        local_accepted
        and azure_di_charge_residual_enabled()
        and _env_on("CDP_AZURE_DI_CHARGE_CORROBORATE", "1")
    )
    effective_gap = gap_class
    if do_corroborate and local_accepted:
        effective_gap = gap_class or "AMBIGUOUS_CHARGE_DIGITS"
    result = run_charge_azure_di_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        gap_class=effective_gap,
        local_accepted=local_accepted,
        settings=settings,
        engine=engine,
        corroborate=do_corroborate,
    )
    promoted = promote_currency_shaped(result)
    effective_review_only = promoted.review_only
    updated = dict(field_row)
    updated["azure_di_residual"] = {
        "attempted": promoted.attempted,
        "configured": promoted.configured,
        "review_only": effective_review_only,
        "currency_shaped": promoted.currency_shaped,
        "reason": promoted.reason,
        "value": promoted.value,
    }
    candidate = residual_candidate_dict(
        promoted,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image_size=image.size,
    )
    if candidate is not None:
        cands = list(updated.get("candidates") or [])
        cands.append(candidate)
        updated["candidates"] = cands
        if not effective_review_only and promoted.currency_shaped and promoted.value:
            local_value = str(cascade.get("value") or "").strip()
            if not local_value:
                for prior in cands[:-1]:
                    seed = str(prior.get("value") or prior.get("raw_value") or "").strip()
                    if seed:
                        local_value = seed
                        break
            # Promote DI to accepted only when it fills empty ink or corroborates
            # local / line-sum (tolerance or digit-drop twin). Non-twin conflict
            # stays as a competing candidate for HITL — never silent override.
            promote_accept = True
            if local_accepted and local_value:
                try:
                    from packages.claim_evidence.line_sum_authority import (
                        amounts_corroborate,
                    )
                except Exception:  # noqa: BLE001
                    amounts_corroborate = None  # type: ignore[assignment]
                if amounts_corroborate is not None and not amounts_corroborate(
                    local_value, promoted.value
                ):
                    promote_accept = False
                    updated["azure_di_residual"]["reason"] = (
                        f"{promoted.reason}|LOCAL_CONFLICT_REVIEW"
                    )
            if promote_accept:
                cascade_out = dict(cascade)
                cascade_out["accepted"] = True
                cascade_out["accept_reason"] = f"AZURE_DI_RESIDUAL:{promoted.reason}"
                cascade_out["value"] = promoted.value
                updated["cascade"] = cascade_out
                updated["status"] = "OBSERVED"
    return updated


def try_charge_azure_di_crop(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    *,
    field_name: str = "charges",
    gap_class: str = "CHARGE_LOCAL_EXHAUSTED",
    engine: Any | None = None,
) -> ChargeAzureDiResidualResult:
    """Service-line helper: DI last resort after local empty/conflict."""
    result = run_charge_azure_di_residual(
        image=image,
        bbox=bbox,
        field_name=field_name,
        gap_class=gap_class,
        local_accepted=False,
        engine=engine,
    )
    return promote_currency_shaped(result)
