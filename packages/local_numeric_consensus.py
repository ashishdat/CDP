"""Field-constrained numeric consensus for noncritical local OCR routes."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class NumericConsensus:
    value: str | None
    support: int
    model_versions: int
    accepted: bool
    reason: str


def reconcile_numeric(
    candidates: list[dict],
    *,
    valid_lengths: set[int],
    minimum_support: int,
    minimum_model_versions: int = 1,
) -> NumericConsensus:
    normalized = []
    models_by_value: dict[str, set[str]] = {}
    for candidate in candidates:
        raw = str(candidate.get("raw_value") or candidate.get("normalized_value") or "")
        digit_runs = re.findall(r"\d+", raw)
        value = next((run for run in digit_runs if len(run) in valid_lengths), None)
        if value is None:
            continue
        normalized.append(value)
        models_by_value.setdefault(value, set()).add(str(candidate.get("model_name") or "unknown"))
    if not normalized:
        return NumericConsensus(None, 0, 0, False, "NO_HARD_VALID_VALUE")
    value, support = Counter(normalized).most_common(1)[0]
    runner_up = Counter(normalized).most_common(2)
    runner_up_support = runner_up[1][1] if len(runner_up) > 1 else 0
    model_versions = len(models_by_value[value])
    accepted = (
        support >= minimum_support
        and support > runner_up_support
        and model_versions >= minimum_model_versions
    )
    return NumericConsensus(
        value if accepted else None,
        support,
        model_versions,
        accepted,
        "CONSENSUS_AND_FORMAT_VALID" if accepted else "CONSENSUS_GATE_FAILED",
    )
