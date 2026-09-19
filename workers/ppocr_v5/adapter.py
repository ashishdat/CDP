"""PaddleOCR 3.x adapter kept out of the stable PaddleOCR 2.x worker image."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PPOCRv5Line:
    text: str
    confidence: float


def _prepare_paddle_cpu_runtime() -> None:
    """Disable OneDNN/PIR paths that crash PP-OCRv5 server on CPU (paddle 3.3)."""
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")
    os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        import paddle

        paddle.set_flags({"FLAGS_use_mkldnn": False})
    except ImportError:
        # Import-time prep only; load() re-raises if paddle is truly missing.
        pass
    except (RuntimeError, ValueError, AttributeError):
        pass


class PPOCRv5Adapter:
    def __init__(
        self,
        pipeline: Any | None = None,
        lang: str = "en",
        *,
        server: bool = True,
    ) -> None:
        self._pipeline = pipeline
        self._lang = lang
        self._server = server

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        _prepare_paddle_cpu_runtime()
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "PP-OCRv5 requires the isolated ppocr-v5 image/dependencies"
            ) from exc
        if self._server:
            self._pipeline = PaddleOCR(
                text_detection_model_name="PP-OCRv5_server_det",
                text_recognition_model_name="PP-OCRv5_server_rec",
                lang=self._lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="cpu",
                enable_mkldnn=False,
            )
        else:
            self._pipeline = PaddleOCR(
                lang=self._lang,
                ocr_version="PP-OCRv5",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="cpu",
                enable_mkldnn=False,
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
