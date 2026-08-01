"""Remove reproducible local build/test artifacts without deleting data volumes."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXACT_DIRECTORIES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
    "idp_claims_platform.egg-info",
}
PREFIXES = (".test-tmp",)
RECURSIVE_NAMES = {"__pycache__"}
RECURSIVE_SUFFIXES = (".tsbuildinfo",)


def _make_writable_and_retry(
    function: Callable[[str], object], path: str, _error: object
) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _safe_remove(path: Path) -> bool:
    resolved = path.resolve()
    if resolved == ROOT or ROOT not in resolved.parents:
        raise RuntimeError(f"refusing to remove path outside repository: {resolved}")
    if path.is_dir():
        try:
            shutil.rmtree(path, onerror=_make_writable_and_retry)
        except PermissionError:
            return False
    elif path.exists():
        try:
            path.unlink()
        except PermissionError:
            return False
    return True


def targets() -> list[Path]:
    selected = [ROOT / name for name in EXACT_DIRECTORIES if (ROOT / name).exists()]
    selected.extend(
        path
        for path in ROOT.iterdir()
        if any(path.name.startswith(prefix) for prefix in PREFIXES)
    )
    selected.extend(
        path
        for path in ROOT.rglob("*")
        if path.is_dir() and path.name in RECURSIVE_NAMES
    )
    selected.extend(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and path.name.endswith(RECURSIVE_SUFFIXES)
    )
    return sorted(set(selected), key=lambda path: len(path.parts), reverse=True)


def main() -> int:
    selected = targets()
    removed = 0
    locked: list[Path] = []
    for path in selected:
        if path.exists():
            if _safe_remove(path):
                removed += 1
            else:
                locked.append(path)
    print(f"Removed {removed} reproducible workspace artifacts.")
    for path in locked:
        print(f"Skipped locked artifact: {path.relative_to(ROOT)}")
    print("Runtime data, evaluation results, model caches, and Docker volumes were preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
