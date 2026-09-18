"""Verification helpers for checksum-pinned extraction releases.

FROZEN manifests require ``status: FROZEN`` and matching hashes.
CANDIDATE manifests require ``status: CANDIDATE`` and still verify that
declared ``configuration_hashes`` match files on disk.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from packages.release_selection import (
    DEFAULT_RELEASE_NAME,
    KNOWN_RELEASES,
    UnknownReleaseError,
    active_release_from_env,
    select_release,
)

__all__ = [
    "DEFAULT_RELEASE_NAME",
    "KNOWN_RELEASES",
    "UnknownReleaseError",
    "active_release_from_env",
    "load_release_manifest",
    "select_release",
    "sha256_file",
    "verify_release_manifest",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_release_manifest(path: Path) -> dict[str, Any]:
    """Load a release YAML into a dict. Raises if missing or not a mapping."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"release manifest is not a mapping: {path}")
    return data


def verify_release_manifest(path: Path) -> None:
    """Verify status and configuration hashes for a release manifest.

    - FROZEN: status must be FROZEN; all hashes must match disk.
    - CANDIDATE: status must be CANDIDATE; all hashes must still match disk.
    - Any other status is rejected.
    """
    manifest = load_release_manifest(path)
    status = manifest.get("status")
    if status == "FROZEN" or status == "CANDIDATE":
        pass
    else:
        raise ValueError(
            f"release manifest status must be FROZEN or CANDIDATE, got {status!r}"
        )

    hashes = manifest.get("configuration_hashes") or {}
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("release manifest has no configuration_hashes")

    for relative, expected in hashes.items():
        actual = sha256_file(Path(relative))
        if actual != expected:
            raise ValueError(
                f"frozen configuration changed without a new release: {relative}"
            )
