"""Document Intelligence confirms a Claude name when one local OCR is not E2.

Claude may replace a confusable single-engine name only when DI reads the same
person. A DI/Claude disagreement stays on the local value.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from PIL import Image

Reader = Callable[[Image.Image, str], str | None]


def _env_on(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _is_vision(engine: str) -> bool:
    text = engine.casefold()
    return any(token in text for token in ("gpt4o", "gpt-4o", "claude", "anthropic"))


def _is_di(engine: str) -> bool:
    text = engine.casefold()
    return "document_intelligence" in text or ("azure" in text and "gpt" not in text)


def maybe_confirm_name_with_azure_di(
    field_row: dict[str, Any],
    *,
    image: Image.Image,
    reader: Reader | None = None,
) -> dict[str, Any]:
    """Attach DI and adopt the Claude name when the two reads normalize equal."""
    updated = dict(field_row)
    if not _env_on("CDP_AZURE_DI_NAME_CONFIRM", "1"):
        return updated
    name = str(field_row.get("field") or "")
    if "name" not in name.casefold():
        return updated
    try:
        from packages.extraction_recovery.cloud_stop_ladder import (
            should_skip_all_cloud,
            should_skip_second_cloud,
        )

        if should_skip_all_cloud(name, field_row) or should_skip_second_cloud(field_row):
            meta = dict(updated.get("cloud_stop_ladder") or {})
            meta["skipped"] = (
                "LOCALS_SETTLED"
                if should_skip_all_cloud(name, field_row)
                else "ONE_CLOUD_SHAPED"
            )
            updated["cloud_stop_ladder"] = meta
            return updated
    except Exception:  # noqa: BLE001
        pass
    bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return updated
    candidates = list(updated.get("candidates") or [])
    if any(_is_di(str(c.get("engine") or "")) for c in candidates):
        return updated
    vision = next(
        (
            c
            for c in candidates
            if _is_vision(str(c.get("engine") or "")) and str(c.get("value") or "").strip()
        ),
        None,
    )
    if vision is None:
        return updated

    from packages.candidate_reconciliation.reconciler import values_conflict_equivalent
    from packages.evidence.normalization import normalize_agreement_value
    from packages.extraction_recovery.field_cascade import semantic_accept
    from packages.extraction_recovery.span_selection import _person_name_from

    vision_value = str(vision.get("value") or "").strip()
    for cand in candidates:
        engine = str(cand.get("engine") or "")
        if _is_vision(engine) or _is_di(engine):
            continue
        local = str(cand.get("value") or cand.get("raw_value") or "").strip()
        if not local:
            continue
        if normalize_agreement_value(name, vision_value) == normalize_agreement_value(
            name, local
        ) or values_conflict_equivalent(name, vision_value, local):
            return updated

    text = ""
    try:
        if reader is not None:
            text = reader(image, name) or ""
        else:
            text = _read_name_crop(image, bbox, name) or ""
    except Exception as exc:  # noqa: BLE001
        attempts = list(updated.get("attempts") or [])
        attempts.append(
            {"engine": "azure_document_intelligence_read", "reason": f"NAME_DI_ERROR:{type(exc).__name__}"}
        )
        updated["attempts"] = attempts
        return updated
    person = _person_name_from(text) or ""
    if not person or not semantic_accept(name, person)[0]:
        attempts = list(updated.get("attempts") or [])
        attempts.append(
            {
                "engine": "azure_document_intelligence_read",
                "reason": "NAME_DI_UNSHAPED",
                "observation": {"text": text[:120]},
            }
        )
        updated["attempts"] = attempts
        return updated
    if normalize_agreement_value(name, person) != normalize_agreement_value(name, vision_value):
        attempts = list(updated.get("attempts") or [])
        attempts.append(
            {
                "engine": "azure_document_intelligence_read",
                "reason": "NAME_DI_DISAGREES",
                "observation": {"text": person},
            }
        )
        updated["attempts"] = attempts
        return updated

    x0, y0, x1, y1 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    candidates.insert(
        0,
        {
            "value": person,
            "raw_value": text.strip() or person,
            "engine": "azure_document_intelligence_read",
            "model_name": "prebuilt-read",
            "model_version": "unknown",
            "preprocessing_variant": "name_azure_di_confirm",
            "preprocessing_version": "cascade-v12-azure-di",
            "raw_confidence": 0.9,
            "calibrated_confidence": 0.9,
            "reason_code": "NAME_DI_CLAUDE_AGREEMENT",
            "latency_ms": 0.0,
            "bounding_box": {
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
                "image_width": float(image.width),
                "image_height": float(image.height),
            },
        },
    )
    updated["candidates"] = candidates
    cascade = dict(updated.get("cascade") or {})
    cascade["accepted"] = True
    cascade["accept_reason"] = "NAME_DI_CLAUDE_AGREEMENT"
    cascade["value"] = vision_value
    updated["cascade"] = cascade
    updated["status"] = "FIELD_ACCEPTED"
    return updated


def _read_name_crop(image: Image.Image, bbox: tuple, field_name: str) -> str | None:
    from packages.azure_di_contracts import (
        azure_document_intelligence_configured,
        build_azure_read_engine,
    )
    from packages.domain.common import BoundingBox
    from packages.domain.enums import ClaimFormType, FieldCriticality
    from packages.ocr.contracts import OCRRequest
    from packages.settings import get_settings

    cfg = get_settings()
    if not azure_document_intelligence_configured(cfg):
        return None
    engine = build_azure_read_engine(cfg)
    x0, y0, x1, y1 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    pad = 8
    crop = image.crop(
        (
            max(0, x0 - pad),
            max(0, y0 - pad),
            min(image.width, x1 + pad),
            min(image.height, y1 + pad),
        )
    ).convert("RGB")
    if crop.width < 160 or crop.height < 64:
        scale = max(160 / max(crop.width, 1), 64 / max(crop.height, 1), 2)
        crop = crop.resize(
            (max(160, int(crop.width * scale)), max(64, int(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
    box = BoundingBox(
        x0=0.0,
        y0=0.0,
        x1=float(crop.width),
        y1=float(crop.height),
        image_width=crop.width,
        image_height=crop.height,
    )
    request = OCRRequest(
        document_id="name-azure-di-confirm",
        page_number=1,
        field_name=field_name,
        field_type="text",
        form_type=ClaimFormType.CMS1500,
        image=crop,
        bounding_box=box,
        criticality=FieldCriticality.CRITICAL,
        scope="FIELD_CROP",
    )
    found = engine.recognize(request)
    if not found:
        return None
    lead = found[0]
    return str(getattr(lead, "raw_value", None) or getattr(lead, "value", None) or "")
