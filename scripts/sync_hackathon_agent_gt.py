#!/usr/bin/env python3
"""Sync shared field truth into the runtime evaluation_data mirror.

Canonical (git-tracked): docs/gt/hackathon_agent_field_truth.json
Mirror (gitignored):     evaluation_data/hackathon_agent_gt/field_truth.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.evaluation.agent_gt_paths import (  # noqa: E402
    CANONICAL_FIELD_TRUTH,
    RUNTIME_FIELD_TRUTH,
    sync_runtime_field_truth,
)


def main() -> int:
    path = sync_runtime_field_truth(force=True)
    if path is None:
        print(f"MISSING canonical GT: {CANONICAL_FIELD_TRUTH}", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    n = len(payload.get("claims") or {})
    print(
        json.dumps(
            {
                "canonical": str(CANONICAL_FIELD_TRUTH.relative_to(ROOT)),
                "runtime": str(RUNTIME_FIELD_TRUTH.relative_to(ROOT)),
                "claims": n,
                "dataset": payload.get("dataset"),
                "stats": payload.get("stats"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
