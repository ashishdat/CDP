"""Optional OpenOCR / SVTRv2 adapter for fixed-form printed field crops.

Redesign role: primary recognition for dates, IDs, and monetary crops.
Default off (``CDP_OPENOCR_SVTR=0``). When enabled but the optional package is
missing, returns UNAVAILABLE so paddle+rapid remain the production path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class OpenOCRSVTRResult:
    text: str | None
    confidence: float
    reason: str
    engine: str = "openocr_svtr"
    attempted: bool = True


def openocr_svtr_enabled() -> bool:
    raw = (os.environ.get("CDP_OPENOCR_SVTR") or "0").strip().casefold()
    return raw not in {"0", "false", "no", "off", ""}


def recognize_openocr_svtr(crop: Image.Image) -> OpenOCRSVTRResult:
    """Recognize printed text from a field crop via OpenOCR/SVTRv2 if installed."""
    if not openocr_svtr_enabled():
        return OpenOCRSVTRResult(
            text=None,
            confidence=0.0,
            reason="OPENOCR_SVTR_DISABLED",
            attempted=False,
        )
    try:
        text, conf, reason = _run_backend(crop)
    except Exception as exc:  # noqa: BLE001 — residual must fail closed
        return OpenOCRSVTRResult(
            text=None,
            confidence=0.0,
            reason=f"OPENOCR_SVTR_ERROR:{type(exc).__name__}",
        )
    if not text:
        return OpenOCRSVTRResult(text=None, confidence=0.0, reason=reason or "OPENOCR_SVTR_EMPTY")
    return OpenOCRSVTRResult(text=text, confidence=conf, reason=reason or "OBSERVED")


def _run_backend(crop: Image.Image) -> tuple[str | None, float, str]:
    """Try OpenOCR → paddleocr SVTR → unavailable."""
    # 1) openocr package (https://github.com/Topdu/OpenOCR)
    try:
        from openocr import OpenOCR  # type: ignore

        engine = getattr(recognize_openocr_svtr, "_engine", None)
        if engine is None:
            engine = OpenOCR(backend="torch", device="cpu")
            recognize_openocr_svtr._engine = engine  # type: ignore[attr-defined]
        import numpy as np

        out = engine(np.asarray(crop.convert("RGB")))
        texts, scores = _parse_openocr_output(out)
        if texts:
            best_i = max(range(len(texts)), key=lambda i: scores[i] if i < len(scores) else 0.0)
            return texts[best_i], (scores[best_i] if best_i < len(scores) else 0.0), "OBSERVED"
        return None, 0.0, "OPENOCR_SVTR_EMPTY"
    except ImportError:
        pass

    # 2) Explicit backend override for tests / custom runtimes
    backend = (os.environ.get("CDP_OPENOCR_SVTR_BACKEND") or "").strip()
    if backend == "mock":
        return None, 0.0, "OPENOCR_SVTR_MOCK_EMPTY"

    return None, 0.0, "OPENOCR_SVTR_UNAVAILABLE"


def _parse_openocr_output(out: Any) -> tuple[list[str], list[float]]:
    texts: list[str] = []
    scores: list[float] = []
    if out is None:
        return texts, scores
    if isinstance(out, dict):
        texts = [str(t).strip() for t in (out.get("texts") or out.get("rec_texts") or []) if str(t).strip()]
        scores = [float(s) for s in (out.get("scores") or out.get("rec_scores") or [])]
        return texts, scores
    if isinstance(out, (list, tuple)):
        for item in out:
            if isinstance(item, dict):
                t = item.get("text") or item.get("transcription")
                if t:
                    texts.append(str(t).strip())
                    scores.append(float(item.get("score") or item.get("confidence") or 0.0))
            elif isinstance(item, (list, tuple)) and item:
                texts.append(str(item[0]).strip())
                scores.append(float(item[1]) if len(item) > 1 else 0.0)
            elif isinstance(item, str) and item.strip():
                texts.append(item.strip())
                scores.append(0.0)
    return texts, scores


def residual_candidate_dict(
    result: OpenOCRSVTRResult,
    *,
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
    field_name: str = "charges",
) -> dict[str, Any] | None:
    if not result.attempted or not result.text:
        return None
    x0, y0, x1, y1 = bbox
    w, h = image_size
    return {
        "value": result.text,
        "raw_value": result.text,
        "engine": result.engine,
        "model_name": "SVTRv2",
        "model_version": "openocr",
        "preprocessing_variant": "OPENOCR_SVTR_CROP",
        "raw_confidence": result.confidence,
        "calibrated_confidence": None,
        "independence_group": "PADDLE_FAMILY",
        "bounding_box": {
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
            "image_width": float(w),
            "image_height": float(h),
        },
        "latency_ms": 0.0,
        "validation_results": ["OPENOCR_SVTR", result.reason],
        "field": field_name,
    }
