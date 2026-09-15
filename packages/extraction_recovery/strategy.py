"""Load the declared field-cascade strategy (YAML source of truth)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_STRATEGY_PATH = Path(__file__).resolve().parents[2] / "config" / "field_cascade_strategy.yaml"


@dataclass(frozen=True)
class FieldStrategy:
    field_name: str
    crop_ladder: tuple[str, ...]
    accept: str
    reject: tuple[str, ...] = ()
    post_miss: tuple[str, ...] = ()
    completion: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class CascadeStrategy:
    version: str
    status: str
    phase: int
    stages: tuple[dict[str, str], ...]
    honesty: tuple[str, ...]
    defaults: dict[str, Any]
    crop_id_aliases: dict[str, str]
    fields: dict[str, FieldStrategy]
    gap_classes: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def strategy_id(self) -> str:
        return self.version


def _parse_field(name: str, raw: dict[str, Any]) -> FieldStrategy:
    return FieldStrategy(
        field_name=name,
        crop_ladder=tuple(str(x) for x in (raw.get("crop_ladder") or ())),
        accept=str(raw.get("accept") or ""),
        reject=tuple(str(x) for x in (raw.get("reject") or ())),
        post_miss=tuple(str(x) for x in (raw.get("post_miss") or ())),
        completion=tuple(str(x) for x in (raw.get("completion") or ())),
        notes=str(raw.get("notes") or ""),
    )


@lru_cache(maxsize=4)
def load_cascade_strategy(path: str | None = None) -> CascadeStrategy:
    """Load and cache the active field-cascade strategy document."""
    strategy_path = Path(path) if path else _STRATEGY_PATH
    payload = yaml.safe_load(strategy_path.read_text(encoding="utf-8")) or {}
    fields_raw = payload.get("fields") or {}
    fields = {
        str(name): _parse_field(str(name), dict(spec or {}))
        for name, spec in fields_raw.items()
    }
    stages = tuple(dict(s) for s in (payload.get("stages") or ()) if isinstance(s, dict))
    return CascadeStrategy(
        version=str(payload.get("version") or "field-cascade-v6"),
        status=str(payload.get("status") or "ACTIVE"),
        phase=int(payload.get("phase") or 6),
        stages=stages,
        honesty=tuple(str(x) for x in (payload.get("honesty") or ())),
        defaults=dict(payload.get("defaults") or {}),
        crop_id_aliases={
            str(k): str(v) for k, v in (payload.get("crop_id_aliases") or {}).items()
        },
        fields=fields,
        gap_classes={
            str(k): dict(v) for k, v in (payload.get("gap_classes") or {}).items()
        },
    )


def crop_ladder_for(field_name: str, strategy: CascadeStrategy | None = None) -> tuple[str, ...]:
    """Resolved CropVariant ids for a field, in strategy order."""
    strat = strategy or load_cascade_strategy()
    spec = strat.fields.get(field_name) or strat.fields.get(field_name.casefold())
    if not spec or not spec.crop_ladder:
        return ()
    aliases = strat.crop_id_aliases
    resolved: list[str] = []
    for ladder_id in spec.crop_ladder:
        variant_id = aliases.get(ladder_id, ladder_id)
        if variant_id not in resolved:
            resolved.append(variant_id)
    return tuple(resolved)


def post_miss_for(field_name: str, strategy: CascadeStrategy | None = None) -> tuple[str, ...]:
    strat = strategy or load_cascade_strategy()
    spec = strat.fields.get(field_name) or strat.fields.get(field_name.casefold())
    return spec.post_miss if spec else ()
