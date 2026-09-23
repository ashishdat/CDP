"""Per-document latency budget for adaptive OCR spend.

Soft (default 18s) and hard (default 22s) cut *optional* work only.
Unsettled charge / patient_dob / insured_id always continue past hard.

Env:
  CDP_DOC_LATENCY_BUDGET=1 (default on)
  CDP_DOC_BUDGET_SOFT_SEC=18
  CDP_DOC_BUDGET_HARD_SEC=22
"""

from __future__ import annotations

import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# Critical identity / finance — never kill when still unsettled.
CRITICAL_FIELDS = frozenset(
    {
        "total_charge",
        "total_charges",
        "charges",
        "charge_amount",
        "patient_dob",
        "insured_id_number",
        "member_id",
        "subscriber_id",
    }
)

# Optional work kinds that soft/hard may skip.
OPTIONAL_KINDS = frozenset(
    {
        "extra_charge_window",  # mid/right after primary already shaped dual-local
        "blank_row_extra_window",  # mid/right on clearly blank primary
        "openocr_svtr",
        "ppocr_v5_server",
        "insured_name_di_confirm",
        "trocr_dob_optional",  # when local already date-shaped (also skip-if-shaped)
        "name_confirm_soft",
    }
)

_ACTIVE: ContextVar["DocLatencyBudget | None"] = ContextVar(
    "cdp_doc_latency_budget", default=None
)


def doc_latency_budget_enabled() -> bool:
    raw = (os.environ.get("CDP_DOC_LATENCY_BUDGET") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class DocLatencyBudget:
    """Wall-clock budget scoped to one claim OCR pass."""

    soft_sec: float = 18.0
    hard_sec: float = 22.0
    started_at: float = field(default_factory=time.perf_counter)
    skips: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "DocLatencyBudget":
        soft = _env_float("CDP_DOC_BUDGET_SOFT_SEC", 18.0)
        hard = _env_float("CDP_DOC_BUDGET_HARD_SEC", 22.0)
        if hard < soft:
            hard = soft
        return cls(
            soft_sec=soft,
            hard_sec=hard,
            enabled=doc_latency_budget_enabled(),
        )

    def elapsed(self) -> float:
        return max(0.0, time.perf_counter() - self.started_at)

    def past_soft(self) -> bool:
        return self.enabled and self.elapsed() >= self.soft_sec

    def past_hard(self) -> bool:
        return self.enabled and self.elapsed() >= self.hard_sec

    def is_critical_field(self, field_name: str | None) -> bool:
        return (field_name or "").casefold() in CRITICAL_FIELDS

    def allow_optional(self, kind: str, *, field_name: str | None = None) -> bool:
        """Return False when soft/hard says skip this optional work."""
        if not self.enabled:
            return True
        kind_key = (kind or "").casefold()
        if kind_key not in OPTIONAL_KINDS and kind_key not in {
            "extra_charge_window",
            "blank_row_extra_window",
        }:
            # Unknown kinds: treat as optional under hard only.
            if self.past_hard():
                self._record_skip(kind_key, field_name, "HARD")
                return False
            return True
        if self.past_hard():
            self._record_skip(kind_key, field_name, "HARD")
            return False
        if self.past_soft():
            self._record_skip(kind_key, field_name, "SOFT")
            return False
        return True

    def allow_cloud_residual(
        self,
        field_name: str | None,
        *,
        unsettled: bool,
    ) -> bool:
        """Cloud residual for unsettled critical fields always allowed.

        Settled / non-critical cloud after hard budget is skipped.
        """
        if not self.enabled:
            return True
        key = (field_name or "").casefold()
        if unsettled and key in CRITICAL_FIELDS:
            return True
        if self.past_hard():
            self._record_skip("cloud_residual", field_name, "HARD_SETTLED_OR_NONCRITICAL")
            return False
        if self.past_soft() and not unsettled:
            self._record_skip("cloud_residual", field_name, "SOFT_SETTLED")
            return False
        return True

    def _record_skip(self, kind: str, field_name: str | None, band: str) -> None:
        self.skips.append(
            {
                "kind": kind,
                "field": field_name,
                "band": band,
                "elapsed_sec": round(self.elapsed(), 3),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "soft_sec": self.soft_sec,
            "hard_sec": self.hard_sec,
            "elapsed_sec": round(self.elapsed(), 3),
            "past_soft": self.past_soft(),
            "past_hard": self.past_hard(),
            "skips": list(self.skips),
        }


def begin_doc_budget(budget: DocLatencyBudget | None = None) -> DocLatencyBudget:
    """Start (or replace) the active per-doc budget for this context."""
    active = budget or DocLatencyBudget.from_env()
    _ACTIVE.set(active)
    return active


def get_doc_budget() -> DocLatencyBudget | None:
    return _ACTIVE.get()


def reset_doc_budget() -> None:
    _ACTIVE.set(None)


def allow_optional(kind: str, *, field_name: str | None = None) -> bool:
    budget = get_doc_budget()
    if budget is None:
        return True
    return budget.allow_optional(kind, field_name=field_name)


def allow_cloud_residual(field_name: str | None, *, unsettled: bool) -> bool:
    budget = get_doc_budget()
    if budget is None:
        return True
    return budget.allow_cloud_residual(field_name, unsettled=unsettled)


def should_early_stop_charge_windows(
    *,
    window_index: int,
    value: str | None,
    dual_local_agree: bool,
    probe_empty: bool,
) -> bool:
    """Adaptive early-stop for charge x-windows (not a global window cap).

    - Blank row: primary empty + probe empty → skip mid/right.
    - Shaped currency: dual-local agree → stop further windows.
    - Soft/hard budget: stop further windows once any shaped amount exists.
    """
    if window_index == 0 and not value and probe_empty:
        return True
    if value and dual_local_agree:
        return True
    if value and not allow_optional("extra_charge_window", field_name="charges"):
        return True
    return False


# HITL attack order for recovery / triage (charge → conflict → identity).
HITL_BUCKET_PRIORITY: dict[str, int] = {
    "charge_field_hitl": 0,
    "charge_conflict_margin": 1,
    "identity_id": 2,
    "identity_dob": 3,
    "bleed_fail_closed": 4,
    "other_hitl": 5,
    "true_stp": 99,
}


def hitl_bucket_sort_key(bucket: str) -> tuple[int, str]:
    return (HITL_BUCKET_PRIORITY.get(bucket, 50), bucket)
