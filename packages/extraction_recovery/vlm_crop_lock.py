"""Cross-process exclusive lock for Claude / gpt-4o crop residual calls.

Parallel claim workers stampeding the vision API inflate wall time (rate
limits, 429 backoff, CPU thrash). One in-flight crop residual at a time keeps
OCR/registration pools parallel while serializing only the slow network hop.

Env:
  CDP_VLM_CROP_LOCK=1|0          master switch (default 1)
  CDP_VLM_CROP_LOCK_PATH=/tmp/cdp_vlm_crop.lock
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

_THREAD_LOCAL = threading.local()


def vlm_crop_lock_enabled() -> bool:
    return (os.environ.get("CDP_VLM_CROP_LOCK") or "1").strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _lock_path() -> Path:
    return Path(os.environ.get("CDP_VLM_CROP_LOCK_PATH") or "/tmp/cdp_vlm_crop.lock")


@contextmanager
def vlm_crop_lock():
    """Exclusive flock around one Claude/gpt-4o crop residual API call."""
    if not vlm_crop_lock_enabled():
        yield
        return
    depth = getattr(_THREAD_LOCAL, "depth", 0)
    if depth > 0:
        _THREAD_LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _THREAD_LOCAL.depth = depth
        return

    import fcntl

    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        _THREAD_LOCAL.depth = 1
        try:
            yield
        finally:
            _THREAD_LOCAL.depth = 0
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
