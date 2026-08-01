"""Versioned evaluation package with lazy public exports."""

from __future__ import annotations

from typing import Any

__all__ = ["EvaluationMetrics", "GroundTruthDataset", "PredictionDataset", "evaluate"]


def __getattr__(name: str) -> Any:
    if name in {"EvaluationMetrics", "evaluate"}:
        from evaluation import metrics
        return getattr(metrics, name)
    if name in {"GroundTruthDataset", "PredictionDataset"}:
        from evaluation import schemas
        return getattr(schemas, name)
    raise AttributeError(name)
