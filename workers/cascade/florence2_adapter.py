"""Lazy local Florence-2 OCR adapter for isolated regional crops."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class Florence2Result:
    text: str | None
    confidence: float
    insufficient_evidence: bool


class Florence2Adapter:
    def __init__(self, model_name: str = "microsoft/Florence-2-base",
                 revision: str | None = None, device: str = "auto",
                 min_confidence: float = 0.55, processor: Any | None = None,
                 model: Any | None = None) -> None:
        self.model_name = model_name
        self.revision = revision
        self.requested_device = device
        self.min_confidence = min_confidence
        self.processor = processor
        self.model = model
        self.device: str | None = None

    def _load(self) -> None:
        if self.processor is not None and self.model is not None:
            self.device = "cpu" if self.requested_device == "auto" else self.requested_device
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as exc:
            raise RuntimeError("Florence-2 requires the optional 'florence' dependencies") from exc
        self.device = ("cuda" if self.requested_device == "auto" and torch.cuda.is_available()
                       else "cpu" if self.requested_device == "auto" else self.requested_device)
        kwargs: dict[str, Any] = {"trust_remote_code": True, "attn_implementation": "eager"}
        if self.revision:
            kwargs["revision"] = self.revision
        self.processor = AutoProcessor.from_pretrained(self.model_name, **kwargs)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_name, **kwargs)
        self.model.to(self.device).eval()

    def recognize(self, crop: Image.Image) -> Florence2Result:
        self._load()
        assert self.processor is not None and self.model is not None
        image = crop.convert("RGB")
        inputs = self.processor(text="<OCR>", images=image, return_tensors="pt")
        inputs = {key: value.to(self.device) if hasattr(value, "to") else value
                  for key, value in inputs.items()}
        generated = self.model.generate(input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"], max_new_tokens=128,
            return_dict_in_generate=True, output_scores=True, do_sample=False)
        decoded = self.processor.batch_decode(generated.sequences, skip_special_tokens=False)[0]
        parsed = self.processor.post_process_generation(decoded, task="<OCR>",
            image_size=(image.width, image.height))
        value = parsed.get("<OCR>") if isinstance(parsed, dict) else parsed
        text = str(value).strip() if value else ""
        confidence = _confidence(generated.scores)
        return Florence2Result(text or None, confidence,
            insufficient_evidence=not text or confidence < self.min_confidence)


def _confidence(scores: Any) -> float:
    if not scores:
        return 0.0
    values = []
    for item in scores:
        probability = (
            item.softmax(dim=-1).max(dim=-1).values.detach().float().mean().cpu().item()
        )
        values.append(max(min(float(probability), 1.0), 1e-9))
    return float(math.exp(sum(math.log(value) for value in values) / len(values)))
