"""Lazy TrOCR adapter for a single, tightly cropped handwritten text line."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image


@dataclass(frozen=True)
class TrOCRResult:
    text: str | None
    confidence: float
    insufficient_evidence: bool


class HandwritingRecognizer(Protocol):
    def recognize(self, crop: Image.Image) -> TrOCRResult: ...
    def recognize_batch(self, crops: list[Image.Image]) -> list[TrOCRResult]: ...


class TrOCRAdapter:
    """Loads Hugging Face TrOCR on first use, not at worker import time."""

    def __init__(
        self,
        model_name: str | None = "microsoft/trocr-base-handwritten",
        device: str = "auto",
        min_confidence: float = 0.55,
        processor: Any | None = None,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self._requested_device = device
        self._min_confidence = min_confidence
        self._processor = processor
        self._model = model
        self._device: str | None = None

    def _load(self) -> None:
        if not self.model_name:
            raise RuntimeError("TrOCR checkpoint is not configured")
        if self._processor is not None and self._model is not None:
            self._device = self._requested_device if self._requested_device != "auto" else "cpu"
            return
        try:
            import torch
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        except ImportError as exc:
            raise RuntimeError(
                "TrOCR requires the optional ML dependencies: pip install '.[ml]'"
            ) from exc
        self._device = (
            "cuda"
            if self._requested_device == "auto" and torch.cuda.is_available()
            else ("cpu" if self._requested_device == "auto" else self._requested_device)
        )
        self._processor = TrOCRProcessor.from_pretrained(self.model_name)
        self._model = VisionEncoderDecoderModel.from_pretrained(self.model_name)
        self._model.to(self._device)
        self._model.eval()

    def recognize(self, crop: Image.Image) -> TrOCRResult:
        return self.recognize_batch([crop])[0]

    def recognize_batch(self, crops: list[Image.Image]) -> list[TrOCRResult]:
        if not crops:
            return []
        self._load()
        assert self._processor is not None and self._model is not None
        images = [crop.convert("RGB") for crop in crops]
        pixel_values = self._processor(images=images, return_tensors="pt").pixel_values
        if hasattr(pixel_values, "to"):
            pixel_values = pixel_values.to(self._device)
        generated = self._model.generate(
            pixel_values,
            return_dict_in_generate=True,
            output_scores=True,
            max_new_tokens=64,
        )
        texts = [
            text.strip()
            for text in self._processor.batch_decode(
                generated.sequences, skip_special_tokens=True
            )
        ]
        confidences = _batch_sequence_confidence(generated.scores, len(texts))
        return [
            TrOCRResult(
                text=text or None,
                confidence=confidence,
                insufficient_evidence=not text or confidence < self._min_confidence,
            )
            for text, confidence in zip(texts, confidences, strict=True)
        ]


def _sequence_confidence(scores: Any) -> float:
    """Geometric mean of generated-token probabilities."""
    if not scores:
        return 0.0
    probabilities: list[float] = []
    for token_scores in scores:
        if hasattr(token_scores, "softmax"):
            maximum = token_scores.softmax(dim=-1).max(dim=-1).values
            value = maximum.detach().float().cpu().item()
        else:
            values = list(token_scores[0] if hasattr(token_scores[0], "__iter__") else token_scores)
            peak = max(values)
            denominator = sum(math.exp(value - peak) for value in values)
            value = 1.0 / denominator
        probabilities.append(max(min(float(value), 1.0), 1e-9))
    return float(math.exp(sum(math.log(value) for value in probabilities) / len(probabilities)))


def _batch_sequence_confidence(scores: Any, batch_size: int) -> list[float]:
    if not scores:
        return [0.0] * batch_size
    per_item: list[list[float]] = [[] for _ in range(batch_size)]
    for token_scores in scores:
        probabilities = token_scores.softmax(dim=-1).max(dim=-1).values
        values = probabilities.detach().float().cpu().tolist()
        for index, value in enumerate(values[:batch_size]):
            per_item[index].append(max(min(float(value), 1.0), 1e-9))
    return [
        float(math.exp(sum(math.log(value) for value in values) / len(values)))
        if values else 0.0
        for values in per_item
    ]
