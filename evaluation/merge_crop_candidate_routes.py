"""Merge original and retuned shadow evidence without replacing either route."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--retuned", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original = json.loads(args.original.read_text(encoding="utf-8"))
    retuned = json.loads(args.retuned.read_text(encoding="utf-8"))
    rows = [dict(row, crop_route="ORIGINAL") for row in original]
    rows.extend(dict(row, crop_route="BORDER_AWARE_AUXILIARY") for row in retuned)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps({"original_candidates": len(original),
        "retuned_candidates": len(retuned), "merged_candidates": len(rows),
        "original_route_preserved": True, "production_promoted": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
