#!/usr/bin/env python3
"""Initialize or validate the production close-out evidence package.

Examples:
  python3 scripts/check_production_closeout.py --init
  python3 scripts/check_production_closeout.py
  python3 scripts/check_production_closeout.py --package-dir /secure/closeout

Exit 0 only when the package authorizes PROMOTE_TO_PRODUCTION with all
organizational approvals. Incomplete packages exit 1 (fail-closed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.production_closeout import (  # noqa: E402
    DEFAULT_PACKAGE_DIR,
    init_closeout_package,
    validate_closeout_package,
    write_validation_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--init",
        action="store_true",
        help="scaffold evidence package from docs/templates/",
    )
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=DEFAULT_PACKAGE_DIR,
        help=f"working package directory (default: {DEFAULT_PACKAGE_DIR})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable validation summary",
    )
    args = parser.parse_args()

    if args.init:
        path = init_closeout_package(args.package_dir)
        print(f"initialized close-out package at {path}")
        print("fill evidence.json + holdout_attestation.json + LAUNCH_RECORD.md")
        print("then re-run without --init")
        return 0

    try:
        validation = validate_closeout_package(args.package_dir)
    except FileNotFoundError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        print("hint: python3 scripts/check_production_closeout.py --init", file=sys.stderr)
        return 1

    report_path = write_validation_report(validation)
    summary = validation.summary()
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"decision: {summary['decision']}")
        print(f"package:  {summary['package_dir']}")
        print(f"report:   {report_path}")
        if summary["issues"]:
            print("issues:")
            for issue in summary["issues"]:
                print(f"  - {issue['code']}: {issue['message']}")
        else:
            print("issues: none")

    if validation.ok:
        print("PROMOTE_TO_PRODUCTION — organizational + readiness gates closed")
        return 0

    print(
        "NEEDS_MORE_DATA — package incomplete; see docs/PRODUCTION_CLOSEOUT_CHECKLIST.md",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
