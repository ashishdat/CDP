"""Table Transformer integration point -- used only when OpenCV
morphology-based grid detection (the default UB service-line table
approach) fails on a specific table (see docs/ARCHITECTURE.md "UB SERVICE
LINES"). Not wired: needs `transformers`/`torch`, not installed on every
dev host -- same lazy-import, `ModelNotAvailableError`-until-configured
pattern as `layoutlmv3_adapter.py`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class TableCell:
    row: int
    column: int
    text: str
    confidence: float


class ModelNotAvailableError(RuntimeError):
    pass


class TableModelAdapter(Protocol):
    def extract_table(self, image: Image.Image) -> list[TableCell]: ...


class TableTransformerAdapter:
    def __init__(self, checkpoint_path: str | None = None) -> None:
        self._checkpoint_path = checkpoint_path

    def extract_table(self, image: Image.Image) -> list[TableCell]:
        if self._checkpoint_path is None:
            raise ModelNotAvailableError(
                "Table Transformer adapter has no checkpoint configured -- this route "
                "should only be reached after OpenCV grid detection fails; treat "
                "unavailability as a signal to escalate further, not to retry"
            )
        try:
            import transformers  # noqa: F401
        except ImportError as exc:
            raise ModelNotAvailableError(
                "transformers/torch are not installed -- install the '[ml]' extras group"
            ) from exc
        raise NotImplementedError(
            "Table Transformer inference is not implemented yet -- see "
            "docs/IMPLEMENTATION_PLAN.md"
        )
