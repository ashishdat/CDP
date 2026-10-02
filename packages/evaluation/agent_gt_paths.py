"""Resolve the shared Hackathon agent field-truth path.

Canonical (git-tracked): ``docs/gt/hackathon_agent_field_truth.json``
  (M048* Hackathon-1000 + optional merged Hackathon-5000 labels)
Hackathon-5000-only: ``docs/gt/hackathon5000_agent_field_truth.json``
Runtime mirror (gitignored): ``evaluation_data/hackathon_agent_gt/field_truth.json``

When scoring a Hackathon-5000 run, prefer the 5000 GT (or a merged canonical
that includes M046*/M047*). Pure M048*-only GT vs 5000 → NO_OVERLAP (not FA=0).
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CANONICAL_FIELD_TRUTH = ROOT / "docs" / "gt" / "hackathon_agent_field_truth.json"
HACKATHON5000_FIELD_TRUTH = (
    ROOT / "docs" / "gt" / "hackathon5000_agent_field_truth.json"
)
RUNTIME_FIELD_TRUTH = (
    ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
)


def resolve_field_truth_path(
    preferred: Path | str | None = None,
    *,
    corpus: str | None = None,
) -> Path | None:
    """Return the first existing field-truth path.

    Order: explicit preferred → ``CDP_FIELD_TRUTH`` env → corpus-specific
    (hackathon5000) → canonical docs/gt → runtime evaluation_data copy.
    """
    candidates: list[Path] = []
    if preferred is not None:
        candidates.append(Path(preferred))
    env_path = (os.environ.get("CDP_FIELD_TRUTH") or "").strip()
    if env_path:
        candidates.append(Path(env_path))
    corp = (corpus or os.environ.get("CDP_FIELD_TRUTH_CORPUS") or "").strip().casefold()
    if corp in {"hackathon5000", "5000", "hackathon-5000"}:
        # 5000-only file first; merged canonical is next (may include M046*).
        candidates.extend([HACKATHON5000_FIELD_TRUTH, CANONICAL_FIELD_TRUTH])
    else:
        candidates.append(CANONICAL_FIELD_TRUTH)
    candidates.append(RUNTIME_FIELD_TRUTH)
    seen: set[Path] = set()
    for path in candidates:
        resolved = path if path.is_absolute() else ROOT / path
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def sync_runtime_field_truth(*, force: bool = True) -> Path | None:
    """Copy canonical GT into the runtime evaluation_data path."""
    if not CANONICAL_FIELD_TRUTH.is_file():
        return None
    RUNTIME_FIELD_TRUTH.parent.mkdir(parents=True, exist_ok=True)
    if (
        not force
        and RUNTIME_FIELD_TRUTH.is_file()
        and RUNTIME_FIELD_TRUTH.read_bytes() == CANONICAL_FIELD_TRUTH.read_bytes()
    ):
        return RUNTIME_FIELD_TRUTH
    RUNTIME_FIELD_TRUTH.write_bytes(CANONICAL_FIELD_TRUTH.read_bytes())
    return RUNTIME_FIELD_TRUTH
