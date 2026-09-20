"""Unit tests for cross-process VLM crop residual lock."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from packages.extraction_recovery.vlm_crop_lock import vlm_crop_lock


def test_vlm_crop_lock_reentrant_and_exclusive(tmp_path, monkeypatch):
    lock_path = tmp_path / "vlm.lock"
    monkeypatch.setenv("CDP_VLM_CROP_LOCK", "1")
    monkeypatch.setenv("CDP_VLM_CROP_LOCK_PATH", str(lock_path))
    order: list[str] = []

    def _job(label: str) -> None:
        with vlm_crop_lock():
            order.append(f"{label}:enter")
            # Nested re-entry must not deadlock the same thread.
            with vlm_crop_lock():
                order.append(f"{label}:nested")
            order.append(f"{label}:exit")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_job, "a"), pool.submit(_job, "b")]
        for fut in futures:
            fut.result(timeout=5)

    # Exclusive: one worker fully completes enter→nested→exit before the other enters.
    assert order in (
        ["a:enter", "a:nested", "a:exit", "b:enter", "b:nested", "b:exit"],
        ["b:enter", "b:nested", "b:exit", "a:enter", "a:nested", "a:exit"],
    )


def test_vlm_crop_lock_can_disable(monkeypatch):
    monkeypatch.setenv("CDP_VLM_CROP_LOCK", "0")
    with vlm_crop_lock():
        pass
