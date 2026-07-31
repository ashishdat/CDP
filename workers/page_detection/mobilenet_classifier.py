"""MobileNetV3-Small page-classification fallback -- the last automated
escalation step before human review in page routing (used when anchor
phrases AND grid/template similarity are both inconclusive, e.g. a heavily
skewed or noisy scan).

Not trained/wired in this phase (needs a labeled page-image dataset and
`torch`/`torchvision`, which -- like `paddlepaddle` -- isn't installed on
every dev host). `PageClassifier` is the interface everything else depends
on; `MobileNetV3PageClassifier` raises `ModelNotAvailableError` until a
checkpoint is configured, so routing code always has a real object to call
and a real (not silent) failure mode when the model isn't available --
callers must treat that exception as "escalate to human review", not
retry-forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class ClassificationResult:
    label: str
    confidence: float


class PageClassifier(Protocol):
    def classify(self, image: Image.Image) -> ClassificationResult: ...


class ModelNotAvailableError(RuntimeError):
    pass


class MobileNetV3PageClassifier:
    def __init__(self, checkpoint_path: str | None = None) -> None:
        self._checkpoint_path = checkpoint_path

    def classify(self, image: Image.Image) -> ClassificationResult:
        if self._checkpoint_path is None:
            raise ModelNotAvailableError(
                "MobileNetV3 page classifier has no checkpoint configured -- "
                "this route should not have been reached without one; treat "
                "as a signal to escalate to human review, not to retry"
            )
        try:
            import torch  # noqa: F401
        except ImportError as exc:
            raise ModelNotAvailableError(
                "torch is not installed -- install the '[ml]' extras group"
            ) from exc
        raise NotImplementedError(
            "MobileNetV3 inference is not implemented yet (Phase 2 scaffolding only) "
            "-- see docs/IMPLEMENTATION_PLAN.md"
        )
