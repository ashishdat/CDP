"""Crop-scoped Azure gpt-4o residual for DOB / member-ID handwriting HITL.

Runs only after local Rapid→Paddle/Tesseract (and DOB TrOCR→Azure DI) leave
the field unshaped, ID-chrome contaminated, or with same-length digit
conflicts between local engines. Crop-only evidence — never a full-page
vision call. Accepts when the value is date-/ID-shaped and the model does
not abstain.

Bakeoff (hard-150 FIELD_INK HITL, 26 docs): DOB shaped 16/17, ID shaped 14/14,
mean ~2.0s/call. See docs/metrics/dob_id_hitl_techstack_v12_3n.md.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span

_DOB_FIELDS = frozenset({"patient_dob", "date_of_birth"})
_ID_FIELDS = frozenset({"insured_id_number", "member_id", "subscriber_id"})
_ID_CHROME = re.compile(
    r"INSURED|NUMBER|PROGRAM|ITEM\s*1|1A\.|FOR\s*PROGRAM|PICA|LAST\s*NAME|MIDDLE",
    re.IGNORECASE,
)
_HANDWRITING_GAPS = frozenset({"HANDWRITING_UNREADABLE", "AMBIGUOUS_DIGIT_FRAGMENTS", ""})


@dataclass(frozen=True)
class Gpt4oCropResidualResult:
    attempted: bool
    configured: bool
    review_only: bool
    value: str | None
    raw_value: str | None
    shaped: bool
    insufficient_evidence: bool
    reason: str
    engine: str = "azure_gpt4o_crop"
    confidence: float | None = None
    validation_results: tuple[str, ...] = ()


class Gpt4oCropRecognizer(Protocol):
    def recognize_fields(
        self,
        crops: Mapping[str, Image.Image],
        *,
        field_types: Mapping[str, str],
        descriptions: Mapping[str, str],
        prior_candidates: Mapping[str, list[str]],
    ) -> Mapping[str, Gpt4oCropResidualResult]: ...


def gpt4o_crop_residual_enabled() -> bool:
    raw = (os.environ.get("CDP_GPT4O_CROP_RESIDUAL") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def gpt4o_crop_accept_enabled() -> bool:
    raw = (os.environ.get("CDP_GPT4O_CROP_ACCEPT") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _normalize(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned or None


def _shape_dob(raw: str | None) -> tuple[str | None, bool]:
    text = _normalize(raw)
    if not text:
        return None, False
    span = select_field_span(text, "DATE", "patient_dob")
    selected = _normalize(span.selected_text) or text
    ok = bool(selected) and semantic_accept("patient_dob", selected)[0]
    return selected, ok


def _shape_id(raw: str | None) -> tuple[str | None, bool]:
    text = _normalize(raw)
    if not text:
        return None, False
    if _ID_CHROME.search(text):
        return text, False
    span = select_field_span(text, "ALPHANUMERIC_ID", "insured_id_number")
    selected = _normalize(span.selected_text) or text
    if _ID_CHROME.search(selected or ""):
        return selected, False
    alnum = re.sub(r"[^A-Za-z0-9]", "", selected or "")
    if len(alnum) < 5 or not re.search(r"\d", alnum):
        return selected, False
    # Reject label-bleed ghosts (NUMBER/PROGRAM fragments fused into alnum).
    if re.search(r"N0?BER|NUMB|PROGRAM|INSURE|ITEM", alnum, re.I):
        return selected, False
    ok = bool(selected) and semantic_accept("insured_id_number", selected)[0]
    return selected, ok


def id_local_needs_gpt4o(value: str | None, *, accepted: bool) -> bool:
    """True when local ID cascade is missing, chrome-contaminated, or too weak."""
    text = _normalize(value) or ""
    if not accepted:
        return True
    if _ID_CHROME.search(text):
        return True
    alnum = re.sub(r"[^A-Za-z0-9]", "", text)
    if len(alnum) < 7:
        return True
    if alnum.isalpha():
        return True
    return False


def id_local_digit_conflict(candidates: list[Mapping[str, Any]] | None) -> bool:
    """True when ≥2 same-length shaped local IDs disagree (genuine digit twins).

    Example: paddle ``909295500`` vs rapid ``909293380``. Confusable-only twins
    (O↔0, J↔U) are excluded — those already have reconcile relief.
    """
    if not candidates:
        return False
    from packages.candidate_reconciliation.reconciler import (
        _canonical_member_id,
        _member_id_is_shaped,
        values_conflict_equivalent,
    )

    shaped: list[str] = []
    for cand in candidates:
        engine = str(cand.get("engine") or "")
        if "gpt4o" in engine.casefold() or "gpt-4o" in engine.casefold():
            continue
        raw = cand.get("value") or cand.get("text")
        text = str(raw or "").strip()
        if not text or not _member_id_is_shaped(text):
            continue
        canon = _canonical_member_id(text)
        if canon and canon not in shaped:
            shaped.append(canon)
    if len(shaped) < 2:
        return False
    for i, left in enumerate(shaped):
        for right in shaped[i + 1 :]:
            if len(left) != len(right) or len(left) < 7:
                continue
            if values_conflict_equivalent("insured_id_number", left, right):
                continue
            return True
    return False


def id_needs_gpt4o(
    value: str | None,
    *,
    accepted: bool,
    candidates: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Weak/chrome local OR same-length digit conflict between local engines."""
    if id_local_needs_gpt4o(value, accepted=accepted):
        return True
    return id_local_digit_conflict(candidates)


def dob_needs_gpt4o(
    *,
    local_accepted: bool,
    trocr_shaped: bool,
    azure_di_shaped: bool,
    gap_class: str | None,
) -> bool:
    if local_accepted or trocr_shaped or azure_di_shaped:
        return False
    gap = (gap_class or "").upper()
    return gap in _HANDWRITING_GAPS or gap in {
        "CALIBRATION_HITL",
        "NORMALIZATION_FAILED",
    }


def _crop_image(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = bbox
    pad = 10
    x0, y0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
    x1, y1 = max(x0 + 1, int(x1) + pad), max(y0 + 1, int(y1) + pad)
    x1, y1 = min(image.width, x1), min(image.height, y1)
    crop = image.crop((x0, y0, x1, y1)).convert("RGB")
    if crop.width < 120 or crop.height < 40:
        scale = max(2, int(140 / max(crop.width, 1)))
        crop = crop.resize(
            (crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS
        )
    return crop


class _AzureGpt4oCropRecognizer:
    """Production recognizer over workers.vlm_fallback Azure adapter."""

    def __init__(self, adapter: Any | None = None) -> None:
        self._adapter = adapter

    def _ensure(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        from packages.settings import Settings
        from workers.vlm_fallback.adapter import AzureOpenAIVisionAdapter

        settings = Settings()
        if not settings.azure_ai_evaluation_enabled:
            raise RuntimeError("Azure gpt-4o evaluation disabled")
        if not (
            settings.azure_openai_endpoint
            and settings.azure_openai_api_key
            and settings.azure_ai_evaluation_deployment
        ):
            raise RuntimeError("Azure OpenAI credentials missing")
        self._adapter = AzureOpenAIVisionAdapter(
            endpoint=settings.azure_openai_endpoint,
            deployment=settings.azure_ai_evaluation_deployment,
            api_version=settings.azure_openai_api_version or "2024-10-21",
            api_key=settings.azure_openai_api_key,
            enabled=True,
            timeout_seconds=45.0,
        )
        return self._adapter

    def recognize_fields(
        self,
        crops: Mapping[str, Image.Image],
        *,
        field_types: Mapping[str, str],
        descriptions: Mapping[str, str],
        prior_candidates: Mapping[str, list[str]],
    ) -> Mapping[str, Gpt4oCropResidualResult]:
        from workers.vlm_fallback.schema import VLMFieldRequest

        adapter = self._ensure()
        pngs: dict[str, bytes] = {}
        requests: list[VLMFieldRequest] = []
        for name, crop in crops.items():
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            pngs[name] = buf.getvalue()
            requests.append(
                VLMFieldRequest(
                    field_name=name,
                    field_type=field_types.get(name, "text"),
                    expected_description=descriptions.get(name, name),
                    prior_ocr_candidates=list(prior_candidates.get(name) or [])[:6],
                )
            )
        results = adapter.extract_fields(pngs, requests)
        out: dict[str, Gpt4oCropResidualResult] = {}
        for item in results:
            raw = _normalize(item.value)
            name = item.field_name
            if name.casefold() in _DOB_FIELDS:
                shaped_val, shaped = _shape_dob(raw)
            elif name.casefold() in _ID_FIELDS:
                shaped_val, shaped = _shape_id(raw)
            else:
                shaped_val, shaped = raw, False
            insuff = bool(item.insufficient_evidence) or not raw
            reason = (
                "GPT4O_ABSTAIN"
                if insuff
                else ("GPT4O_SHAPED" if shaped else "GPT4O_UNSHAPED")
            )
            out[name] = Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value=shaped_val if shaped else raw,
                raw_value=raw,
                shaped=shaped and not insuff,
                insufficient_evidence=insuff,
                reason=reason,
                confidence=float(item.confidence),
                validation_results=("AZURE_GPT4O_CROP",),
            )
        return out


def _dob_cell_bboxes(
    bbox: tuple[int, int, int, int],
) -> list[tuple[int, int, int, int]]:
    """Split a DOB ROI into approximate MM / DD / YY cells (equal thirds)."""
    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    third = max(1, width // 3)
    cells = []
    for i in range(3):
        cx0 = x0 + i * third
        cx1 = x1 if i == 2 else x0 + (i + 1) * third
        cells.append((cx0, y0, max(cx0 + 1, cx1), y1))
    return cells


def _dob_description(prior: list[str], *, cell_mode: bool = False) -> str:
    base = (
        "Handwritten CMS-1500 box 3 patient date of birth with MM DD YY cells. "
        "Return MM/DD/YYYY when digits are visible. Colon/comma/period between "
        "digit groups are damaged separators (e.g. 7:30.77 means 07/30/1977). "
        "Abstain only if the crop is empty or truly illegible."
    )
    if cell_mode:
        base = (
            "Three cropped CMS-1500 DOB cells (month, day, year). "
            "Read each cell's handwritten digits and return one MM/DD/YYYY. "
            "Abstain only if cells are empty."
        )
    hints = [p for p in prior if p and p.strip()]
    if hints:
        base += " Prior OCR saw: " + " | ".join(hints[:4]) + "."
    return base


def run_gpt4o_crop_residual(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str,
    prior_candidates: list[str] | None = None,
    engine: Gpt4oCropRecognizer | None = None,
) -> Gpt4oCropResidualResult:
    if not gpt4o_crop_residual_enabled():
        return Gpt4oCropResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            shaped=False,
            insufficient_evidence=True,
            reason="GPT4O_CROP_DISABLED",
        )
    name = (field_name or "").casefold()
    if name not in _DOB_FIELDS and name not in _ID_FIELDS:
        return Gpt4oCropResidualResult(
            attempted=False,
            configured=True,
            review_only=True,
            value=None,
            raw_value=None,
            shaped=False,
            insufficient_evidence=True,
            reason="GPT4O_FIELD_UNSUPPORTED",
        )
    prior = list(prior_candidates or [])
    crop = _crop_image(image, bbox)
    if name in _DOB_FIELDS:
        ftype, desc = "date", _dob_description(prior)
    else:
        desc = (
            "Handwritten or typed CMS-1500 box 1a insured/member ID. "
            "Alphanumeric ID only — not phone, NPI, EIN, or printed labels. "
            "Read every digit carefully; when prior OCR engines disagree on "
            "digits, choose the ID that matches the ink."
        )
        if prior:
            desc += " Prior OCR saw: " + " | ".join(prior[:4]) + "."
        ftype = "code"
    recognizer = engine or _AzureGpt4oCropRecognizer()

    def _call(
        crop_image: Image.Image,
        *,
        description: str,
        field_type: str,
    ) -> Gpt4oCropResidualResult:
        try:
            mapped = recognizer.recognize_fields(
                {field_name: crop_image},
                field_types={field_name: field_type},
                descriptions={field_name: description},
                prior_candidates={field_name: prior},
            )
        except Exception as exc:  # noqa: BLE001 — residual must fail closed
            return Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value=None,
                raw_value=None,
                shaped=False,
                insufficient_evidence=True,
                reason=f"GPT4O_ERROR:{type(exc).__name__}",
                validation_results=(f"ERROR:{exc}"[:160],),
            )
        return mapped.get(field_name) or Gpt4oCropResidualResult(
            attempted=True,
            configured=True,
            review_only=True,
            value=None,
            raw_value=None,
            shaped=False,
            insufficient_evidence=True,
            reason="GPT4O_EMPTY_RESPONSE",
        )

    # Single full-box crop first.
    result = _call(crop, description=desc, field_type=ftype)

    # DOB abstain → MM/DD/YY cell-split retry (DI hint already in description).
    if name in _DOB_FIELDS and (result.insufficient_evidence or not result.shaped):
        cells = _dob_cell_bboxes(bbox)
        try:
            cell_imgs = [_crop_image(image, cell) for cell in cells]
            widths = [c.width for c in cell_imgs]
            height = max(c.height for c in cell_imgs)
            strip = Image.new(
                "RGB", (sum(widths) + 4, height), color=(255, 255, 255)
            )
            x = 0
            for cell_img in cell_imgs:
                strip.paste(cell_img, (x, 0))
                x += cell_img.width + 2
            retry = _call(
                strip,
                description=_dob_description(prior, cell_mode=True),
                field_type="date",
            )
            if retry.shaped and not retry.insufficient_evidence:
                return Gpt4oCropResidualResult(
                    attempted=True,
                    configured=True,
                    review_only=retry.review_only,
                    value=retry.value,
                    raw_value=retry.raw_value,
                    shaped=True,
                    insufficient_evidence=False,
                    reason="GPT4O_CELL_SPLIT_SHAPED",
                    engine=retry.engine,
                    confidence=retry.confidence,
                    validation_results=tuple(retry.validation_results)
                    + ("GPT4O_CELL_SPLIT",),
                )
        except Exception:  # noqa: BLE001
            pass
    return result


def residual_candidate_dict(
    result: Gpt4oCropResidualResult,
    *,
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> dict[str, Any] | None:
    if not result.attempted or not result.value:
        return None
    width, height = image_size
    x0, y0, x1, y1 = bbox
    conf = float(result.confidence) if result.confidence is not None else 0.9
    return {
        "value": result.value,
        "raw_value": result.raw_value or result.value,
        "engine": result.engine,
        "model_name": "gpt-4o",
        "model_version": "azure-openai",
        "preprocessing_variant": "gpt4o_crop_residual",
        "preprocessing_version": "cascade-v12-3n",
        "raw_confidence": conf,
        "calibrated_confidence": conf,
        "confidence": conf,
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
        "bbox": list(bbox),
        "image_width": float(width),
        "image_height": float(height),
        "reason": result.reason,
    }


def maybe_attach_gpt4o_crop_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    gap_class: str | None = None,
    engine: Gpt4oCropRecognizer | None = None,
) -> dict[str, Any]:
    """Attach gpt-4o crop residual for DOB (post DI) or weak/chrome ID."""
    updated = dict(field_row)
    name = str(field_row.get("field") or "")
    key = name.casefold()
    cascade = dict(field_row.get("cascade") or {})
    local_accepted = bool(cascade.get("accepted"))
    bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return updated

    prior = [
        str(c.get("value") or c.get("text") or "").strip()
        for c in (field_row.get("candidates") or [])
        if (c.get("value") or c.get("text"))
    ]

    if key in _DOB_FIELDS:
        trocr = field_row.get("trocr_residual") or {}
        di = field_row.get("azure_di_residual") or {}
        if not dob_needs_gpt4o(
            local_accepted=local_accepted,
            trocr_shaped=bool(trocr.get("date_shaped") and not trocr.get("review_only")),
            azure_di_shaped=bool(di.get("date_shaped") and not di.get("review_only")),
            gap_class=gap_class,
        ):
            return updated
    elif key in _ID_FIELDS:
        cascade_value = None
        for step in cascade.get("steps") or []:
            if step.get("accepted"):
                cascade_value = step.get("selected_value")
                break
        if cascade_value is None and prior:
            cascade_value = prior[0]
        if not id_needs_gpt4o(
            cascade_value,
            accepted=local_accepted,
            candidates=list(field_row.get("candidates") or []),
        ):
            return updated
    else:
        return updated

    result = run_gpt4o_crop_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        prior_candidates=prior,
        engine=engine,
    )
    accept = gpt4o_crop_accept_enabled()
    effective_review_only = result.review_only and not (accept and result.shaped)
    updated["gpt4o_crop_residual"] = {
        "attempted": result.attempted,
        "configured": result.configured,
        "review_only": effective_review_only,
        "shaped": result.shaped,
        "insufficient_evidence": result.insufficient_evidence,
        "reason": result.reason,
        "value": result.value,
        "confidence": result.confidence,
    }
    promoted = result
    if accept and result.shaped and result.review_only:
        promoted = Gpt4oCropResidualResult(
            attempted=result.attempted,
            configured=result.configured,
            review_only=False,
            value=result.value,
            raw_value=result.raw_value,
            shaped=True,
            insufficient_evidence=False,
            reason="GPT4O_SHAPED_ACCEPTED",
            engine=result.engine,
            confidence=result.confidence,
            validation_results=tuple(
                v for v in result.validation_results if v != "SHADOW_REVIEW_ONLY"
            )
            or ("AZURE_GPT4O_CROP",),
        )
        updated["gpt4o_crop_residual"]["review_only"] = False
        updated["gpt4o_crop_residual"]["reason"] = promoted.reason
    candidate = residual_candidate_dict(
        promoted,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image_size=(image.width, image.height),
    )
    if candidate is not None:
        candidates = list(updated.get("candidates") or [])
        candidates.insert(0, candidate)
        updated["candidates"] = candidates
        if promoted.shaped and not promoted.review_only:
            cascade_out = dict(cascade)
            cascade_out["accepted"] = True
            cascade_out["accept_reason"] = f"GPT4O_CROP_RESIDUAL:{promoted.reason}"
            updated["cascade"] = cascade_out
            updated["status"] = "FIELD_ACCEPTED"
    return updated
