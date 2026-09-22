#!/usr/bin/env python3
"""Fail closed unless tip geometry cohort field accuracy is ≥ 95%.

Reads the measured agent-GT accuracy summary for the current geometry tip.
Does not invent labels or loosen FA gates. Exit 0 only when:
  exact_accuracy ≥ 0.95
  accepted_field_precision ≥ 0.995 (or 1.0 when scored)
  false_accepts == 0

Default tip: evaluation_results/hackathon_gt_accuracy_geo_95_gate/summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "evaluation_results/hackathon_gt_accuracy_geo_95_gate/summary.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT)
    parser.add_argument("--min-exact", type=float, default=0.95)
    parser.add_argument("--min-precision", type=float, default=0.995)
    args = parser.parse_args()
    path = args.summary if args.summary.is_absolute() else ROOT / args.summary
    if not path.is_file():
        print(f"FAIL missing accuracy summary: {path}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    exact = float(data.get("exact_accuracy") or 0.0)
    precision = float(data.get("accepted_field_precision") or 0.0)
    fa = int(data.get("false_accepts") or 0)
    ok = exact >= args.min_exact and precision >= args.min_precision and fa == 0
    print(
        json.dumps(
            {
                "ok": ok,
                "exact_accuracy": exact,
                "accepted_field_precision": precision,
                "false_accepts": fa,
                "min_exact": args.min_exact,
                "min_precision": args.min_precision,
                "summary": str(path.relative_to(ROOT)),
                "claims_scored": data.get("claims_scored"),
                "field_count": data.get("field_count"),
                "quarantined_fields": data.get("quarantined_fields"),
                "release_gate_eligible": data.get("release_gate_eligible"),
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
