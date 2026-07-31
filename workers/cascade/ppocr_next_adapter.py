"""Shadow PP-OCRv5/v6 recognition-only adapter for isolated field crops."""

from __future__ import annotations

import time
from typing import Protocol

import cv2
import numpy as np
from PIL import Image, ImageOps

from packages.ocr.contracts import OCRCandidate, OCRRequest
from workers.cascade.line_segmentation import segment_text_lines
from workers.retry.alternate_preprocessing import upscale


class RecognitionBackend(Protocol):
    def predict(self, image) -> tuple[str, float]: ...


class PaddleTextRecognitionBackend:
    def __init__(self, model_name: str) -> None:
        try:
            from paddleocr import TextRecognition
        except ImportError as exc:
            raise RuntimeError("PaddleOCR 3.x recognition runtime is not installed") from exc
        self._model = TextRecognition(model_name=model_name)

    def predict(self, image) -> tuple[str, float]:
        # PaddleOCR 3.x accepts ndarray/path inputs, not PIL Image instances.
        array = np.ascontiguousarray(np.asarray(image.convert("RGB")))
        outputs = list(self._model.predict(input=array, batch_size=1))
        if not outputs:
            return "", 0.0
        payload = outputs[0].json
        if callable(payload):
            payload = payload()
        data = payload.get("res", payload)
        return str(data.get("rec_text", "")), float(data.get("rec_score", 0.0))


class PPOCRNextRecognitionEngine:
    """Adds border/upscale and bypasses detection for an already isolated line."""

    provider_version = "shadow-v1"

    def __init__(
        self,
        model_name: str = "PP-OCRv6_medium_rec",
        *,
        border_px: int = 16,
        scale: int = 2,
        preprocessing_profile: str = "original",
        backend: RecognitionBackend | None = None,
    ) -> None:
        self._model_name = model_name
        self._border_px = border_px
        self._scale = scale
        self._preprocessing_profile = preprocessing_profile
        self._backend = backend

    @property
    def engine_name(self) -> str:
        return "paddleocr_recognition_only"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return "paddleocr-3.x"

    def recognize(self, request: OCRRequest) -> list[OCRCandidate]:
        started = time.perf_counter()
        crop = self._preprocess(request.image.convert("RGB"))
        crop = ImageOps.expand(crop, border=self._border_px, fill="white")
        crop = upscale(crop, self._scale)
        if self._backend is None:
            self._backend = PaddleTextRecognitionBackend(self._model_name)
        backend = self._backend
        lines = segment_text_lines(crop)
        recognized = [backend.predict(line) for line in lines]
        text = "\n".join(value.strip() for value, _ in recognized if value.strip())
        confidence = (
            sum(score for _, score in recognized) / len(recognized)
            if recognized else 0.0
        )
        return [OCRCandidate(
            value=text.strip() or None,
            raw_value=text,
            engine=self.engine_name,
            model_name=self.model_name,
            model_version=self.model_version,
            preprocessing_variant=(
                f"{self._preprocessing_profile}_white_border_"
                f"{self._border_px}_upscale_{self._scale}x"
            ),
            raw_confidence=confidence,
            calibrated_confidence=None,
            bounding_box=request.bounding_box,
            latency_ms=(time.perf_counter() - started) * 1000,
            validation_results=(
                "SHADOW_REVIEW_ONLY",
                "GEOMETRY_PRESERVING_LINE_RECONSTRUCTION"
                if len(lines) > 1 else "SINGLE_LINE_RECOGNITION",
            ),
        )]

    def _preprocess(self, image: Image.Image) -> Image.Image:
        if self._preprocessing_profile == "original":
            return image
        gray = np.asarray(image.convert("L"))
        if self._preprocessing_profile == "clahe":
            output = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        elif self._preprocessing_profile == "adaptive_threshold":
            output = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 11,
            )
        elif self._preprocessing_profile == "sharpen":
            output = cv2.filter2D(
                gray, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            )
        else:
            raise ValueError(
                f"unsupported preprocessing profile: {self._preprocessing_profile}"
            )
        return Image.fromarray(output).convert("RGB")
