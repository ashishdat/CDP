"""Cross-process OCR inference lock (Paddle/Rapid critical sections only).

Claim-level flock around the entire ``ocr_from_geometry`` subprocess serializes
unzip/warp/JSON as well as inference. Prefer this module so prep work overlaps
across workers while only GPU/CPU-critical extract calls take the exclusive lock.

Env:
  CDP_OCR_LOCK=1|0           master switch (default 1)
  CDP_OCR_LOCK_SCOPE=inference|process   (default inference)
  CDP_OCR_LOCK_PATH=/tmp/cdp_ocr.lock
  CDP_OCR_LOCK_ENGINES=paddleocr,rapidocr   engines that take the lock
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

_THREAD_LOCAL = threading.local()


def ocr_lock_enabled() -> bool:
    return (os.environ.get("CDP_OCR_LOCK") or "1").strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def ocr_lock_scope() -> str:
    scope = (os.environ.get("CDP_OCR_LOCK_SCOPE") or "inference").strip().casefold()
    return scope if scope in {"inference", "process"} else "inference"


def locked_engines() -> set[str]:
    raw = (
        os.environ.get("CDP_OCR_LOCK_ENGINES") or "paddleocr,rapidocr"
    ).strip().casefold()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _lock_path() -> Path:
    return Path(os.environ.get("CDP_OCR_LOCK_PATH") or "/tmp/cdp_ocr.lock")


@contextmanager
def ocr_inference_lock(engine: str | None = None):
    """Exclusive flock around one heavy OCR inference call."""
    if not ocr_lock_enabled() or ocr_lock_scope() != "inference":
        yield
        return
    if engine is not None and engine.casefold() not in locked_engines():
        yield
        return
    # Re-entrant for nested recognize→extract within the same thread.
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


@contextmanager
def ocr_process_lock():
    """Legacy whole-process lock (cascade runner). No-op when scope=inference."""
    if not ocr_lock_enabled() or ocr_lock_scope() == "inference":
        yield
        return
    import fcntl

    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
