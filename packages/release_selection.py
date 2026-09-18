"""Explicit extraction-release selection (no silent fallback).

Operators pin the active release with ``CDP_RELEASE_MANIFEST`` (path) or
``CDP_PIPELINE_RELEASE`` (logical name). When neither is set, the safe
default is ``extraction-v2``. Unknown names raise; V3 is never selected
unless configured.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_RELEASE_NAME = "extraction-v2"
RELEASES_DIR = Path("config/releases")

# Logical release names that map to governed manifests under config/releases/.
KNOWN_RELEASES: dict[str, Path] = {
    "extraction-v2": RELEASES_DIR / "extraction-v2.yaml",
    "extraction-v3": RELEASES_DIR / "extraction-v3.yaml",
}


class UnknownReleaseError(KeyError):
    """Raised when a release name is not in the governed catalog."""


def select_release(name: str | Path) -> Path:
    """Resolve an explicit release name or path to a manifest Path.

    Accepts ``extraction-v2``, ``extraction-v3``, or a filesystem path.
    Does not fall back to another release when the name is unknown.
    """
    if isinstance(name, Path):
        path = name
        if not path.is_file():
            raise UnknownReleaseError(f"release manifest not found: {path}")
        return path

    text = str(name).strip()
    if not text:
        raise UnknownReleaseError("release name is empty")

    if text in KNOWN_RELEASES:
        path = KNOWN_RELEASES[text]
        if not path.is_file():
            raise UnknownReleaseError(f"known release missing on disk: {text} -> {path}")
        return path

    path = Path(text)
    if path.is_file():
        return path

    raise UnknownReleaseError(
        f"unknown release {text!r}; expected one of "
        f"{sorted(KNOWN_RELEASES)} or an existing manifest path"
    )


def active_release_from_env(
    environ: dict[str, str] | None = None,
) -> Path:
    """Return the configured release manifest path.

    Precedence:
    1. ``CDP_RELEASE_MANIFEST`` — explicit path (or known name)
    2. ``CDP_PIPELINE_RELEASE`` — logical name (or path)
    3. default ``extraction-v2`` (safety: never silently activate V3)
    """
    env = environ if environ is not None else os.environ
    for key in ("CDP_RELEASE_MANIFEST", "CDP_PIPELINE_RELEASE"):
        value = env.get(key)
        if value is not None and str(value).strip():
            return select_release(str(value).strip())
    return select_release(DEFAULT_RELEASE_NAME)
