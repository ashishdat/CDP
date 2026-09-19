"""Governed redesign-stack loader and role helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_STACK_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "architecture" / "redesign_stack_v1.yaml"
)


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    technology: tuple[str, ...]
    role: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RedesignStack:
    version: str
    status: str
    capabilities: dict[str, CapabilitySpec]
    charge_residual_ladder: tuple[str, ...]
    independence_groups: dict[str, tuple[str, ...]]
    honesty: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def gpt_is_monetary_authority(self) -> bool:
        llm = self.capabilities.get("llm_vlm")
        if llm is None:
            return False
        return bool(llm.raw.get("monetary_authority", False))


@lru_cache(maxsize=4)
def load_redesign_stack(path: str | None = None) -> RedesignStack:
    stack_path = Path(path) if path else _STACK_PATH
    payload = yaml.safe_load(stack_path.read_text(encoding="utf-8")) or {}
    caps_raw = payload.get("capabilities") or {}
    capabilities: dict[str, CapabilitySpec] = {}
    for name, spec in caps_raw.items():
        if not isinstance(spec, dict):
            continue
        tech = spec.get("technology") or []
        if isinstance(tech, str):
            tech = [tech]
        capabilities[str(name)] = CapabilitySpec(
            name=str(name),
            technology=tuple(str(t) for t in tech),
            role=str(spec.get("role") or ""),
            status=str(spec.get("status") or "UNKNOWN"),
            raw=dict(spec),
        )
    groups = {
        str(k): tuple(str(x) for x in (v or ()))
        for k, v in (payload.get("independence_groups") or {}).items()
    }
    return RedesignStack(
        version=str(payload.get("version") or "redesign-stack-v1"),
        status=str(payload.get("status") or "ACTIVE"),
        capabilities=capabilities,
        charge_residual_ladder=tuple(
            str(x) for x in (payload.get("charge_residual_ladder") or ())
        ),
        independence_groups=groups,
        honesty=tuple(str(x) for x in (payload.get("honesty") or ())),
        raw=dict(payload),
    )


def capability(name: str, stack: RedesignStack | None = None) -> CapabilitySpec | None:
    return (stack or load_redesign_stack()).capabilities.get(name)


def independence_group_for_engine(engine: str, stack: RedesignStack | None = None) -> str:
    eng = (engine or "").strip().casefold()
    groups = (stack or load_redesign_stack()).independence_groups
    for group, members in groups.items():
        for member in members:
            m = member.casefold()
            if m == eng or m in eng or eng in m:
                return group
    return eng or "unknown"


def gpt_may_be_sole_monetary_authority(stack: RedesignStack | None = None) -> bool:
    """Always False under redesign-stack-v1 honesty."""
    return (stack or load_redesign_stack()).gpt_is_monetary_authority
