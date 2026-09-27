"""Resolve the shared Hackathon agent field-truth path.

Canonical (git-tracked): ``docs/gt/hackathon_agent_field_truth.json``
Runtime mirror (gitignored): ``evaluation_data/hackathon_agent_gt/field_truth.json``

Product FA scoring must use this shared GT. Hackathon-5000 (M046/M047*) has
**zero document overlap** with the labeled M048* set — treat that as
incomplete FA, never as FA=0.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CANONICAL_FIELD_TRUTH = ROOT / "docs" / "gt" / "hackathon_agent_field_truth.json"
RUNTIME_FIELD_TRUTH = (
    ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
)


def resolve_field_truth_path(
    preferred: Path | str | None = None,
) -> Path | None:
    """Return the first existing field-truth path.

    Order: explicit preferred → canonical docs/gt → runtime evaluation_data copy.
    """
    candidates: list[Path] = []
    if preferred is not None:
        candidates.append(Path(preferred))
    candidates.extend([CANONICAL_FIELD_TRUTH, RUNTIME_FIELD_TRUTH])
    for path in candidates:
        if path.is_file():
            return path
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
