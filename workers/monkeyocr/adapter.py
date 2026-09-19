"""MonkeyOCR stub for complex table residual (redesign CANDIDATE).

Enable with ``CDP_MONKEYOCR=1`` once a backend is installed. Until then this
adapter reports UNAVAILABLE and never blocks the geometric table path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class MonkeyOCRResult:
    text: str | None
    structure: dict[str, Any] | None
    reason: str
    engine: str = "monkeyocr"
    attempted: bool = True
    review_only: bool = True


def monkeyocr_enabled() -> bool:
    raw = (os.environ.get("CDP_MONKEYOCR") or "0").strip().casefold()
    return raw not in {"0", "false", "no", "off", ""}


def recognize_table(crop: Image.Image) -> MonkeyOCRResult:
    if not monkeyocr_enabled():
        return MonkeyOCRResult(
            text=None,
            structure=None,
            reason="MONKEYOCR_DISABLED",
            attempted=False,
        )
    # Stub until MonkeyOCR runtime is provisioned in the environment build.
    return MonkeyOCRResult(
        text=None,
        structure=None,
        reason="MONKEYOCR_UNAVAILABLE",
        attempted=True,
        review_only=True,
    )
