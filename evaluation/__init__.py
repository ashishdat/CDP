"""Versioned, field-level extraction accuracy evaluation."""

from evaluation.metrics import EvaluationMetrics, evaluate
from evaluation.schemas import GroundTruthDataset, PredictionDataset

__all__ = ["EvaluationMetrics", "GroundTruthDataset", "PredictionDataset", "evaluate"]
