"""Selective risk-coverage tracking for critical field acceptance.

Does **not** fit thresholds. Records adjudicated accept/reject outcomes by
evidence pattern so a later calibration pass can choose the highest coverage
whose upper risk bound stays ≤ 0.005 (99.5% precision).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any


@dataclass
class EvidencePatternStats:
    pattern: str
    accepts: int = 0
    errors: int = 0

    @property
    def n(self) -> int:
        return self.accepts

    @property
    def error_rate(self) -> float:
        return (self.errors / self.accepts) if self.accepts else 0.0

    def wilson_upper(self, z: float = 1.645) -> float:
        """One-sided ~95% Wilson upper bound on error rate."""
        n = self.accepts
        if n <= 0:
            return 1.0
        p = self.errors / n
        denom = 1.0 + z * z / n
        centre = p + z * z / (2.0 * n)
        spread = z * sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)
        return min(1.0, (centre + spread) / denom)

    def meets_precision_gate(self, max_risk: float = 0.005) -> bool:
        return self.accepts > 0 and self.wilson_upper() <= max_risk


@dataclass
class RiskCoverageLedger:
    """Accumulate adjudicated critical-field outcomes by evidence pattern."""

    patterns: dict[str, EvidencePatternStats] = field(default_factory=dict)
    target_error_free_accepts: int = 600

    def record(
        self,
        pattern: str,
        *,
        accepted: bool,
        correct: bool | None,
    ) -> None:
        if not accepted:
            return
        row = self.patterns.setdefault(pattern, EvidencePatternStats(pattern=pattern))
        row.accepts += 1
        if correct is False:
            row.errors += 1

    def coverage_curve(
        self, *, max_risk: float = 0.005
    ) -> list[dict[str, Any]]:
        """Sort patterns by ascending Wilson upper risk; cumulative coverage."""
        ordered = sorted(
            self.patterns.values(),
            key=lambda r: (r.wilson_upper(), -r.accepts, r.pattern),
        )
        kept = 0
        errors = 0
        total = sum(r.accepts for r in self.patterns.values()) or 1
        curve: list[dict[str, Any]] = []
        for row in ordered:
            if not row.meets_precision_gate(max_risk):
                break
            kept += row.accepts
            errors += row.errors
            curve.append(
                {
                    "pattern": row.pattern,
                    "accepts": row.accepts,
                    "errors": row.errors,
                    "wilson_upper": round(row.wilson_upper(), 6),
                    "cumulative_coverage": round(kept / total, 4),
                    "cumulative_precision": round(
                        1.0 - (errors / kept if kept else 0.0), 6
                    ),
                }
            )
        return curve

    def readiness(self) -> dict[str, Any]:
        total_accepts = sum(r.accepts for r in self.patterns.values())
        total_errors = sum(r.errors for r in self.patterns.values())
        return {
            "adjudicated_accepts": total_accepts,
            "adjudicated_errors": total_errors,
            "target_error_free_accepts": self.target_error_free_accepts,
            "ready_to_fit_thresholds": total_accepts >= self.target_error_free_accepts
            and total_errors == 0,
            "patterns": len(self.patterns),
        }
