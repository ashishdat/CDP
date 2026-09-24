"""Apply and enforce FAST vs PRODUCT run profiles.

Recurring bug: sample runners default to FAST (residuals off) then a product
gate is scored on that ledger — STP collapses and looks like “arch failed
again.” Tip-seed PASSes on the 1000 corpus hide the same gap on new Drive zips.

Contract:
- FAST → never product-gate eligible
- PRODUCT → gate eligible (live residuals on)
- TIP_SEED → gate eligible only with an explicit allow flag
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = ROOT / "config" / "run_profiles_v1.yaml"
MANIFEST_NAME = "run_manifest.json"


class ProfileError(ValueError):
    """Invalid or gate-ineligible profile."""


@dataclass(frozen=True)
class RunProfile:
    name: str
    purpose: str
    gate_eligible: bool
    requires_allow_tip_seed_for_gate: bool
    description: str
    env: dict[str, str]


@lru_cache(maxsize=4)
def load_profiles(path: str | None = None) -> dict[str, RunProfile]:
    cfg_path = Path(path) if path else DEFAULT_PROFILES
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    out: dict[str, RunProfile] = {}
    for name, body in dict(raw.get("profiles") or {}).items():
        out[str(name).upper()] = RunProfile(
            name=str(name).upper(),
            purpose=str(body.get("purpose") or ""),
            gate_eligible=bool(body.get("gate_eligible")),
            requires_allow_tip_seed_for_gate=bool(
                body.get("requires_allow_tip_seed_for_gate")
            ),
            description=str(body.get("description") or "").strip(),
            env={str(k): str(v) for k, v in dict(body.get("env") or {}).items()},
        )
    if "FAST" not in out or "PRODUCT" not in out:
        raise ProfileError(f"run_profiles missing FAST/PRODUCT: {cfg_path}")
    return out


def product_residual_flags(path: str | None = None) -> tuple[str, ...]:
    cfg_path = Path(path) if path else DEFAULT_PROFILES
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    flags = raw.get("product_residual_flags") or []
    return tuple(str(f) for f in flags)


def apply_profile_env(
    profile_name: str,
    env: dict[str, str] | None = None,
    *,
    profiles_path: str | None = None,
) -> tuple[dict[str, str], RunProfile]:
    """Return a copy of env with the named profile applied."""
    profiles = load_profiles(profiles_path)
    key = profile_name.strip().upper()
    if key not in profiles:
        raise ProfileError(f"unknown run profile: {profile_name}")
    profile = profiles[key]
    out = dict(env if env is not None else os.environ)
    out.update(profile.env)
    return out, profile


def detect_live_profile(
    environ: Mapping[str, str] | None = None,
    *,
    profiles_path: str | None = None,
) -> str:
    """Classify current env as PRODUCT / FAST / MIXED from residual kill-switches."""
    env = environ if environ is not None else os.environ
    flags = product_residual_flags(profiles_path)
    if not flags:
        return "UNKNOWN"

    def _on(key: str) -> bool:
        return str(env.get(key) or "").strip() in {"1", "true", "yes", "on"}

    states = [_on(k) for k in flags]
    if all(states):
        return "PRODUCT"
    if not any(states):
        return "FAST"
    return "MIXED"


def write_run_manifest(
    out_dir: Path,
    *,
    profile: str,
    dataset_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    profiles = load_profiles()
    key = profile.strip().upper()
    meta = profiles.get(key)
    payload: dict[str, Any] = {
        "profile": key,
        "gate_eligible": bool(meta.gate_eligible) if meta else False,
        "requires_allow_tip_seed_for_gate": bool(
            meta.requires_allow_tip_seed_for_gate
        )
        if meta
        else False,
        "purpose": meta.purpose if meta else "",
        "dataset_id": dataset_id,
        "detected_live_profile": detect_live_profile(),
        "residual_flags": {
            flag: os.environ.get(flag) for flag in product_residual_flags()
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(dict(extra))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MANIFEST_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_run_manifest(ledger_dir: Path) -> dict[str, Any] | None:
    path = ledger_dir / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def gate_allows_profile(
    manifest: Mapping[str, Any] | None,
    *,
    allow_tip_seed: bool = False,
    allow_missing_manifest: bool = False,
    allow_fast: bool = False,
) -> tuple[bool, str]:
    """Return (ok, reason). Product gate must call this before PASS."""
    if manifest is None:
        if allow_missing_manifest:
            return True, "MANIFEST_MISSING_ALLOWED"
        return False, "RUN_MANIFEST_MISSING:refuse_unprofiled_ledger"

    profile = str(manifest.get("profile") or "").upper()
    if profile == "PRODUCT":
        return True, "PRODUCT"
    if profile == "TIP_SEED":
        if allow_tip_seed:
            return True, "TIP_SEED_ALLOWED"
        return (
            False,
            "TIP_SEED_REQUIRES_ALLOW:pass --allow-tip-seed only for known tip replay",
        )
    if profile == "FAST":
        if allow_fast:
            return True, "FAST_ALLOWED_DEBUG"
        return (
            False,
            "FAST_NOT_GATE_ELIGIBLE:re-run with --product/--full (residuals on)",
        )
    if profile == "MIXED":
        return False, "MIXED_PROFILE_NOT_GATE_ELIGIBLE:set PRODUCT residuals consistently"
    return False, f"UNKNOWN_PROFILE:{profile or 'empty'}"
