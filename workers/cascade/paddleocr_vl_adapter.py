"""Review-only PaddleOCR-VL element recognizer for regional claim crops."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class PaddleOCRVLResult:
    text: str | None
    insufficient_evidence: bool


class PaddleOCRVLAdapter:
    def __init__(self, model_name: str = "PaddlePaddle/PaddleOCR-VL",
                 revision: str | None = None, device: str = "auto",
                 max_new_tokens: int = 64, processor: Any | None = None,
                 model: Any | None = None) -> None:
        self.model_name = model_name
        self.revision = revision
        self.requested_device = device
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
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as exc:
            raise RuntimeError("PaddleOCR-VL shadow dependencies are not installed") from exc
        self.device = ("cuda" if self.requested_device == "auto" and torch.cuda.is_available()
                       else "cpu" if self.requested_device == "auto" else self.requested_device)
        kwargs: dict[str, Any] = {"trust_remote_code": True}
        if self.revision:
            kwargs["revision"] = self.revision
        self.processor = AutoProcessor.from_pretrained(self.model_name, **kwargs)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_name, **kwargs)
        self.model.to(self.device).eval()

    def recognize(self, crop: Image.Image) -> PaddleOCRVLResult:
        self._load()
        assert self.processor is not None and self.model is not None
        messages = [{"role": "user", "content": [
            {"type": "image", "image": crop.convert("RGB")},
            {"type": "text", "text": "OCR:"},
        ]}]
        inputs = self.processor.apply_chat_template(messages, tokenize=True,
            add_generation_prompt=True, return_dict=True, return_tensors="pt")
        inputs = inputs.to(self.device) if hasattr(inputs, "to") else inputs
        generated = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens,
            do_sample=False, use_cache=True)
        prompt_length = inputs["input_ids"].shape[1]
        text = self.processor.batch_decode(
            generated[:, prompt_length:], skip_special_tokens=True
        )[0].strip()
        return PaddleOCRVLResult(text or None, insufficient_evidence=not bool(text))
