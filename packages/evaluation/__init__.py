"""Evaluation package — agent GT scoring for product FA gates."""

from packages.evaluation.agent_gt_score import (
    exact_match,
    load_agent_gt,
    normalize_field,
    score_merged_against_agent_gt,
)

__all__ = [
    "exact_match",
    "load_agent_gt",
    "normalize_field",
    "score_merged_against_agent_gt",
]
