"""Complex table discovery residual (redesign CANDIDATE, REVIEW_ONLY).

Tries PaddleOCR-VL when ``CDP_PADDLEOCR_VL_TABLE=1``, then MonkeyOCR when
``CDP_MONKEYOCR=1``. Never auto-accepts monetary or claim fields — structure
hints are for HITL / review assistance only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class ComplexTableResult:
    text: str | None
    structure: dict[str, Any] | None
    reason: str
    engines_tried: tuple[str, ...] = ()
    attempted: bool = True
    review_only: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


def _env_on(name: str, default: str = "0") -> bool:
    return (os.environ.get(name) or default).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
        "",
    }


def complex_tables_enabled() -> bool:
    return _env_on("CDP_PADDLEOCR_VL_TABLE") or _env_on("CDP_MONKEYOCR")


def recognize_complex_table(crop: Image.Image) -> ComplexTableResult:
    if not complex_tables_enabled():
        return ComplexTableResult(
            text=None,
            structure=None,
            reason="COMPLEX_TABLES_DISABLED",
            attempted=False,
        )

    tried: list[str] = []
    meta: dict[str, Any] = {}

    if _env_on("CDP_PADDLEOCR_VL_TABLE"):
        tried.append("paddleocr_vl")
        vl = _try_paddleocr_vl(crop)
        meta["paddleocr_vl"] = vl.get("reason")
        if vl.get("text"):
            return ComplexTableResult(
                text=vl["text"],
                structure=vl.get("structure"),
                reason="PADDLEOCR_VL_OBSERVED|REVIEW_ONLY",
                engines_tried=tuple(tried),
                review_only=True,
                meta=meta,
            )

    if _env_on("CDP_MONKEYOCR"):
        tried.append("monkeyocr")
        try:
            from workers.monkeyocr import recognize_table
        except ImportError:
            meta["monkeyocr"] = "IMPORT_ERROR"
        else:
            result = recognize_table(crop)
            meta["monkeyocr"] = result.reason
            if result.text:
                return ComplexTableResult(
                    text=result.text,
                    structure=result.structure,
                    reason=f"{result.reason}|REVIEW_ONLY",
                    engines_tried=tuple(tried),
                    review_only=True,
                    meta=meta,
                )

    if not tried:
        return ComplexTableResult(
            text=None,
            structure=None,
            reason="COMPLEX_TABLES_DISABLED",
            attempted=False,
        )
    return ComplexTableResult(
        text=None,
        structure=None,
        reason="COMPLEX_TABLES_UNAVAILABLE",
        engines_tried=tuple(tried),
        review_only=True,
        meta=meta,
    )


def _try_paddleocr_vl(crop: Image.Image) -> dict[str, Any]:
    try:
        from workers.cascade.paddleocr_vl_adapter import PaddleOCRVLAdapter
    except ImportError:
        return {"reason": "PADDLEOCR_VL_IMPORT_ERROR", "text": None}
    try:
        adapter = PaddleOCRVLAdapter()
        result = adapter.recognize(crop)
    except Exception as exc:  # noqa: BLE001 — residual fail-closed
        return {"reason": f"PADDLEOCR_VL_ERROR:{type(exc).__name__}", "text": None}
    if result.insufficient_evidence or not result.text:
        return {"reason": "PADDLEOCR_VL_EMPTY", "text": None}
    return {
        "reason": "OBSERVED",
        "text": result.text,
        "structure": {"source": "paddleocr_vl", "raw": result.text},
    }
