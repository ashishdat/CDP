"""Truth-blind consensus for locally recognized names, cities, and placeholders."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class TextConsensus:
    value: str | None
    support: int
    runner_up_support: int
    accepted: bool
    reason: str


def _tokens(raw: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", raw.upper())


def reconcile_text(
    candidates: list[dict], *, selector: str, minimum_support: int,
) -> TextConsensus:
    values: list[str] = []
    for candidate in candidates:
        raw = str(candidate.get("raw_value") or candidate.get("normalized_value") or "")
        tokens = _tokens(raw)
        if not tokens:
            continue
        if selector == "whole":
            value = " ".join(tokens)
        elif selector == "first":
            value = tokens[0]
        elif selector == "middle":
            value = tokens[len(tokens) // 2] if len(tokens) % 2 else ""
        elif selector == "last":
            value = tokens[-1]
        else:
            raise ValueError(f"unsupported selector: {selector}")
        if value:
            values.append(value)
    if not values:
        return TextConsensus(None, 0, 0, False, "NO_TEXT_VALUE")
    ranked = Counter(values).most_common(2)
    value, support = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    accepted = support >= minimum_support and support > runner_up
    return TextConsensus(
        value if accepted else None,
        support,
        runner_up,
        accepted,
        "CONSENSUS_AND_MARGIN_VALID" if accepted else "CONSENSUS_GATE_FAILED",
    )
