"""PaddleOCR 3.x adapter kept out of the stable PaddleOCR 2.x worker image."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PPOCRv5Line:
    text: str
    confidence: float


class PPOCRv5Adapter:
    def __init__(self, pipeline: Any | None = None, lang: str = "en") -> None:
        self._pipeline = pipeline
        self._lang = lang

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "PP-OCRv5 requires the isolated ppocr-v5 image/dependencies"
            ) from exc
        self._pipeline = PaddleOCR(
            lang=self._lang,
            ocr_version="PP-OCRv5",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )

    def recognize(self, crop: Image.Image) -> list[PPOCRv5Line]:
        self._load()
        assert self._pipeline is not None
        output = self._pipeline.predict(np.asarray(crop.convert("RGB")))
        lines: list[PPOCRv5Line] = []
        for result in output:
            payload = getattr(result, "json", result)
            if callable(payload):
                payload = payload()
            if isinstance(payload, dict) and "res" in payload:
                payload = payload["res"]
            texts = payload.get("rec_texts", []) if isinstance(payload, dict) else []
            scores = payload.get("rec_scores", []) if isinstance(payload, dict) else []
            lines.extend(
                PPOCRv5Line(str(text).strip(), float(score))
                for text, score in zip(texts, scores, strict=False)
                if str(text).strip()
            )
        return lines
