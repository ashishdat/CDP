"""Specialist monetary crop recognizer — restricted digit vocabulary."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageOps

from packages.ocr_portfolio.monetary_variants import CropVariant

_CURRENCY_RE = re.compile(
    r"\$?\d{1,3}(?:,\d{3})*\.\d{2}|\$?\d{1,6}(?:\.\d{2})?|\(\d+\.\d{2}\)|CR\s*\d+\.\d{2}"
)
_WHITELIST = set("0123456789,.$()-CR ")


@dataclass(frozen=True)
class MonetaryRead:
    value: str | None
    raw_text: str
    engine: str
    variant_id: str
    confidence: float
    reason: str


@dataclass
class MonetaryRecognizeResult:
    best: MonetaryRead | None
    attempts: list[MonetaryRead] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "best": None
            if self.best is None
            else {
                "value": self.best.value,
                "raw_text": self.best.raw_text,
                "engine": self.best.engine,
                "variant_id": self.best.variant_id,
                "confidence": self.best.confidence,
                "reason": self.best.reason,
            },
            "attempts": [
                {
                    "value": a.value,
                    "raw_text": a.raw_text,
                    "engine": a.engine,
                    "variant_id": a.variant_id,
                    "confidence": a.confidence,
                    "reason": a.reason,
                }
                for a in self.attempts
            ],
        }


def _env_on(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
        "",
    }


def shape_monetary(text: str) -> str | None:
    cleaned = "".join(ch for ch in (text or "") if ch in _WHITELIST).strip()
    if not cleaned:
        return None
    candidates: list[str] = []
    m = _CURRENCY_RE.search(cleaned.replace(" ", ""))
    if m:
        amount = m.group(0).lstrip("$").replace(",", "")
        if amount.upper().startswith("CR"):
            amount = amount[2:].strip()
        if amount.startswith("(") and amount.endswith(")"):
            amount = amount[1:-1]
        if "." in amount and re.fullmatch(r"\d+\.\d{2}", amount):
            return amount
        if "." not in amount and re.fullmatch(r"\d{2,6}", amount):
            # Defer to ranked digit-soup handling below (6404 → 640.00).
            cleaned = amount
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return None
    if re.fullmatch(r"\d{2,6}", digits):
        candidates = [f"{digits}.00"]
        if len(digits) >= 4:
            candidates.append(f"{digits[:-2]}.{digits[-2:]}")
            if digits[-1] in {"4", "1"}:
                candidates.append(f"{digits[:-1]}.00")
        ranked: list[tuple[float, str]] = []
        for cand in candidates:
            try:
                val = float(cand)
            except ValueError:
                continue
            if not re.fullmatch(r"\d+\.\d{2}", cand):
                continue
            if not (1.0 <= val <= 99999.99):
                continue
            dollars = cand.split(".", 1)[0]
            score = 2.0 if 2 <= len(dollars) <= 4 else 1.0
            if cand.endswith(".00"):
                score += 0.5
            if len(digits) >= 4 and digits[-1] in {"4", "1"} and dollars == digits[:-1]:
                score += 2.0
            if dollars == digits and len(digits) >= 4 and digits[-1] in {"4", "1"}:
                score -= 2.0
            ranked.append((score, cand))
        if ranked:
            ranked.sort(key=lambda x: (-x[0], len(x[1])))
            return ranked[0][1]
    return None


def monetary_variants_extended(crop: Image.Image) -> list[CropVariant]:
    """Governed variants including nearest-neighbour, bicubic, adaptive threshold."""
    base = crop.convert("RGB")
    out: list[CropVariant] = [CropVariant("original", base)]
    w, h = base.size
    gray = ImageOps.grayscale(base)

    for scale in (2, 4):
        nw, nh = max(1, w * scale), max(1, h * scale)
        out.append(
            CropVariant(
                f"nn_{scale}x",
                gray.resize((nw, nh), Image.Resampling.NEAREST).convert("RGB"),
            )
        )
        out.append(
            CropVariant(
                f"bicubic_{scale}x",
                gray.resize((nw, nh), Image.Resampling.BICUBIC).convert("RGB"),
            )
        )

    out.append(CropVariant("inverted", ImageOps.invert(base.convert("RGB"))))
    arr = np.asarray(gray, dtype=np.uint8)
    adaptive = cv2.adaptiveThreshold(
        arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    out.append(CropVariant("adaptive_threshold", Image.fromarray(adaptive).convert("RGB")))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    closed = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, kernel)
    out.append(CropVariant("morph_close", Image.fromarray(closed).convert("RGB")))
    horiz = cv2.morphologyEx(
        arr,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(8, w // 4), 1)),
    )
    out.append(
        CropVariant("line_removal", Image.fromarray(cv2.subtract(arr, horiz)).convert("RGB"))
    )
    pad_x, pad_y = max(1, w // 20), max(1, h // 20)
    out.append(
        CropVariant(
            "expanded_context",
            ImageOps.expand(base, border=(pad_x, pad_y), fill=(255, 255, 255)),
        )
    )
    # Isolated connected components (largest ink blob).
    _, bw = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bw)
    if n_labels > 1:
        # Skip background label 0; pick largest component.
        areas = stats[1:, cv2.CC_STAT_AREA]
        idx = int(np.argmax(areas)) + 1
        x, y, bw_w, bw_h, _ = stats[idx]
        pad = 2
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(arr.shape[1], x + bw_w + pad), min(arr.shape[0], y + bw_h + pad)
        if x1 > x0 and y1 > y0:
            blob = gray.crop((x0, y0, x1, y1)).convert("RGB")
            out.append(CropVariant("connected_component", blob))
    return out


EngineFn = Callable[[Image.Image], tuple[str, float]]


def recognize_monetary_crop(
    crop: Image.Image,
    *,
    engines: dict[str, EngineFn] | None = None,
    max_variants: int | None = None,
) -> MonetaryRecognizeResult:
    """Run controlled variants × engines; return best shaped monetary value."""
    if not _env_on("CDP_MONETARY_VARIANTS", "1"):
        return MonetaryRecognizeResult(best=None, attempts=[])

    variants = monetary_variants_extended(crop)
    if max_variants is not None:
        variants = variants[: max(1, max_variants)]

    engine_map = engines or {}
    attempts: list[MonetaryRead] = []
    best: MonetaryRead | None = None

    for variant in variants:
        for eng_name, fn in engine_map.items():
            try:
                text, conf = fn(variant.image)
            except Exception as exc:  # noqa: BLE001
                attempts.append(
                    MonetaryRead(
                        value=None,
                        raw_text="",
                        engine=eng_name,
                        variant_id=variant.variant_id,
                        confidence=0.0,
                        reason=f"ERROR:{type(exc).__name__}",
                    )
                )
                continue
            shaped = shape_monetary(text or "")
            read = MonetaryRead(
                value=shaped,
                raw_text=text or "",
                engine=eng_name,
                variant_id=variant.variant_id,
                confidence=float(conf or 0.0),
                reason="SHAPED" if shaped else "UNSHAPED",
            )
            attempts.append(read)
            if shaped and (best is None or conf > best.confidence):
                best = read
            if shaped and _env_on("CDP_MONETARY_VARIANTS_EARLY_STOP", "1"):
                return MonetaryRecognizeResult(best=best, attempts=attempts)

    return MonetaryRecognizeResult(best=best, attempts=attempts)
