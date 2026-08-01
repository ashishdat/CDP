"""Lazy local GOT-OCR2 adapter for isolated regional crops."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class GOTOCR2Result:
    text: str | None
    confidence: float
    insufficient_evidence: bool


class GOTOCR2Adapter:
    def __init__(self, model_name: str = "stepfun-ai/GOT-OCR-2.0-hf",
                 revision: str | None = None, device: str = "auto",
                 min_confidence: float = 0.55, max_new_tokens: int = 128,
                 processor: Any | None = None,
                 model: Any | None = None) -> None:
        self.model_name = model_name
        self.revision = revision
        self.requested_device = device
        self.min_confidence = min_confidence
        self.max_new_tokens = max_new_tokens
        self.processor = processor
        self.model = model
        self.device: str | None = None

    def _load(self) -> None:
        if self.processor is not None and self.model is not None:
            self.device = "cpu" if self.requested_device == "auto" else self.requested_device
            return
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as exc:
            raise RuntimeError("GOT-OCR2 requires the optional 'got_ocr2' dependencies") from exc
        self.device = ("cuda" if self.requested_device == "auto" and torch.cuda.is_available()
                       else "cpu" if self.requested_device == "auto" else self.requested_device)
        kwargs: dict[str, Any] = {}
        if self.revision:
            kwargs["revision"] = self.revision
        self.processor = AutoProcessor.from_pretrained(self.model_name, **kwargs)
        self.model = AutoModelForImageTextToText.from_pretrained(self.model_name, **kwargs)
        self.model.to(self.device).eval()

    def recognize(self, crop: Image.Image) -> GOTOCR2Result:
        self._load()
        assert self.processor is not None and self.model is not None
        inputs = self.processor(crop.convert("RGB"), return_tensors="pt")
        inputs = {key: value.to(self.device) if hasattr(value, "to") else value
                  for key, value in inputs.items()}
        generated = self.model.generate(**inputs, do_sample=False,
            max_new_tokens=self.max_new_tokens,
            tokenizer=self.processor.tokenizer,
            stop_strings="<|im_end|>",
            return_dict_in_generate=True, output_scores=True)
        prompt_length = inputs["input_ids"].shape[1]
        sequence = generated.sequences[:, prompt_length:]
        text = self.processor.batch_decode(sequence, skip_special_tokens=True)[0].strip()
        confidence = _confidence(generated.scores)
        return GOTOCR2Result(text or None, confidence,
            insufficient_evidence=not text or confidence < self.min_confidence)


def _confidence(scores: Any) -> float:
    if not scores:
        return 0.0
    probabilities = [
        max(min(float(item.softmax(dim=-1).max(dim=-1).values.detach().float().mean().cpu().item()), 1.0), 1e-9)
        for item in scores
    ]
    return float(math.exp(sum(math.log(value) for value in probabilities) / len(probabilities)))
