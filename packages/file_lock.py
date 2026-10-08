"""Cross-process advisory exclusive locks for Windows and POSIX."""
from __future__ import annotations
import errno
import math
import os
import time


def lock_exclusive(handle, *, timeout_seconds=None):
    deadline = None
    if timeout_seconds is not None:
        if isinstance(timeout_seconds, bool) or not math.isfinite(float(timeout_seconds)) or float(timeout_seconds) < 0:
            raise ValueError("lock timeout must be finite and nonnegative")
        deadline = time.monotonic() + float(timeout_seconds)

    def wait_or_timeout():
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("EXCLUSIVE_LOCK_WAIT_EXHAUSTED")
        time.sleep(0.05 if deadline is None else min(0.05, max(0, deadline-time.monotonic())))

    if os.name != "nt":
        import fcntl
        if deadline is None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            return
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                wait_or_timeout()
    import msvcrt
    position = handle.tell()
    try:
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                wait_or_timeout()
    finally:
        handle.seek(position)


def unlock(handle):
    if os.name != "nt":
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    import msvcrt
    position = handle.tell()
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.seek(position)
