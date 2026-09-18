#!/usr/bin/env python3
"""Resolve dependency profiles in isolation and reject exclusive conflicts.

Exit codes:
  0  All supported profiles resolve; exclusive conflict correctly rejected.
  1  A supported profile failed pip resolution (dry-run).
  2  Exclusive pair (florence + got_ocr2) unexpectedly resolved together.
  3  Usage / environment error (bad args, missing pip, etc.).

Examples:
  python scripts/check_dependency_profiles.py
  python scripts/check_dependency_profiles.py --profile runtime-florence
  python scripts/check_dependency_profiles.py --list
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Supported install profiles: (name, pip install target relative to ROOT).
# Each is resolved alone; florence and got_ocr2 must never share an env.
SUPPORTED_PROFILES: dict[str, str] = {
    "runtime-core": "-e .[runtime-core]",
    "runtime-handwriting": "-e .[runtime-handwriting]",
    "runtime-florence": "-e .[runtime-florence]",
    "runtime-got-ocr2": "-e .[runtime-got-ocr2]",
    "runtime-learned-match": "-e .[runtime-learned-match]",
    "runtime-cloud-residual": "-e .[runtime-cloud-residual]",
    "dev": "-e .[dev]",
    "ocr": "-e .[ocr]",
    "handwriting": "-e .[handwriting]",
    "learned-match": "-e .[learned-match]",
    "florence": "-e .[florence]",
    "got_ocr2": "-e .[got_ocr2]",
    "docling": "-e .[docling]",
    "ml": "-e .[ml]",
}

# Profiles checked by default in CI (skip heavy optional extras like docling
# unless requested). Still includes both exclusive VLM extras — each alone.
DEFAULT_PROFILES = (
    "runtime-core",
    "runtime-handwriting",
    "runtime-florence",
    "runtime-got-ocr2",
    "runtime-learned-match",
    "runtime-cloud-residual",
    "dev",
)

EXCLUSIVE_COMBINED = "-e .[florence,got_ocr2]"


def _run_pip_dry_run(target: str) -> subprocess.CompletedProcess[str]:
    """Resolve *target* with pip install --dry-run (no install)."""
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--disable-pip-version-check",
        *target.split(),
    ]
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_pip_dry_run_isolated(target: str) -> subprocess.CompletedProcess[str]:
    """Create a throwaway venv and dry-run resolve *target* inside it.

    Used when the ambient env already has conflicting pins; isolation keeps
    resolution honest without a full download/install cycle.
    """
    with tempfile.TemporaryDirectory(prefix="dep-profile-") as tmp:
        venv_dir = Path(tmp) / "venv"
        create = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if create.returncode != 0:
            return create
        pip = venv_dir / "bin" / "pip"
        cmd = [
            str(pip),
            "install",
            "--dry-run",
            "--disable-pip-version-check",
            *target.split(),
        ]
        return subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def resolve_profile(name: str, target: str, *, isolated: bool) -> tuple[bool, str]:
    runner = _run_pip_dry_run_isolated if isolated else _run_pip_dry_run
    result = runner(target)
    if result.returncode == 0:
        return True, f"OK  {name}: resolves ({target})"
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    tail = "\n".join(detail[-12:]) if detail else f"exit {result.returncode}"
    return False, f"FAIL {name}: {target}\n{tail}"


def check_exclusive_conflict(*, isolated: bool) -> tuple[bool, str]:
    """Return (rejected_ok, message). rejected_ok means combined install failed."""
    runner = _run_pip_dry_run_isolated if isolated else _run_pip_dry_run
    result = runner(EXCLUSIVE_COMBINED)
    if result.returncode != 0:
        return True, "OK  exclusive check: florence+got_ocr2 correctly fails to resolve"
    return False, (
        "FAIL exclusive check: florence+got_ocr2 unexpectedly resolved together "
        f"({EXCLUSIVE_COMBINED})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Profile name to check (repeatable). Default: CI default set.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List supported profile names and exit 0.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check every supported profile (not only the CI default set).",
    )
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="Resolve inside a temporary venv (slower; use if ambient pins interfere).",
    )
    parser.add_argument(
        "--skip-exclusive-check",
        action="store_true",
        help="Skip the florence+got_ocr2 combined failure check.",
    )
    args = parser.parse_args(argv)

    if args.list:
        for name in sorted(SUPPORTED_PROFILES):
            print(f"{name}\t{SUPPORTED_PROFILES[name]}")
        return 0

    if args.profiles:
        selected = args.profiles
    elif args.all:
        selected = list(SUPPORTED_PROFILES)
    else:
        selected = list(DEFAULT_PROFILES)

    unknown = [name for name in selected if name not in SUPPORTED_PROFILES]
    if unknown:
        print(f"Unknown profile(s): {', '.join(unknown)}", file=sys.stderr)
        print("Use --list to see supported names.", file=sys.stderr)
        return 3

    # Quick capability check for --dry-run.
    probe = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or "--dry-run" not in (probe.stdout or ""):
        print("pip install --dry-run is required (pip>=22.2).", file=sys.stderr)
        return 3

    failures: list[str] = []
    for name in selected:
        ok, message = resolve_profile(
            name, SUPPORTED_PROFILES[name], isolated=args.isolated
        )
        print(message)
        if not ok:
            failures.append(name)

    exclusive_ok = True
    if not args.skip_exclusive_check:
        exclusive_ok, exclusive_msg = check_exclusive_conflict(isolated=args.isolated)
        print(exclusive_msg)
        if not exclusive_ok:
            return 2

    if failures:
        print(f"\n{len(failures)} profile(s) failed resolution: {', '.join(failures)}")
        return 1

    print("\nAll selected dependency profiles resolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
