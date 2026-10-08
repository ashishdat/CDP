import multiprocessing
import pytest
from packages.file_lock import lock_exclusive, unlock


def _contend(path, ready, acquired):
    with open(path, "a+") as handle:
        ready.set()
        lock_exclusive(handle)
        try:
            acquired.set()
        finally:
            unlock(handle)


def test_cross_process_exclusion_and_release(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready, acquired = ctx.Event(), ctx.Event()
    path = str(tmp_path / "shared.lock")
    with open(path, "a+") as handle:
        lock_exclusive(handle)
        child = ctx.Process(target=_contend, args=(path, ready, acquired))
        child.start()
        try:
            assert ready.wait(20)
            assert not acquired.wait(0.3)
        finally:
            unlock(handle)
        try:
            assert acquired.wait(20)
            child.join(20)
            assert child.exitcode == 0
        finally:
            if child.is_alive():
                child.terminate()
                child.join()


def test_locks_are_reentrant_and_release_after_exception(tmp_path, monkeypatch):
    from packages.ocr_runtime_lock import ocr_inference_lock
    from packages.extraction_recovery.vlm_crop_lock import vlm_crop_lock
    monkeypatch.setenv("CDP_OCR_LOCK", "1")
    monkeypatch.setenv("CDP_OCR_LOCK_SCOPE", "inference")
    monkeypatch.setenv("CDP_OCR_LOCK_PATH", str(tmp_path / "ocr.lock"))
    monkeypatch.setenv("CDP_VLM_CROP_LOCK", "1")
    monkeypatch.setenv("CDP_VLM_CROP_LOCK_PATH", str(tmp_path / "vlm.lock"))
    for factory in [lambda: ocr_inference_lock("paddleocr"), vlm_crop_lock]:
        with pytest.raises(ValueError):
            with factory(), factory():
                raise ValueError("release on failure")
        with factory():
            pass


def test_azure_slot_persists_timestamp_with_portable_lock(tmp_path):
    from workers.cascade.azure_di_backend import wait_for_azure_di_slot
    current = [100.0]
    waits = []
    def sleep(seconds):
        waits.append(seconds)
        current[0] += seconds
    path = tmp_path / "azure-slot"
    for _ in range(2):
        wait_for_azure_di_slot(interval_seconds=2, sleeper=sleep,
                               now=lambda: current[0], slot_path=path)
    assert waits == [2.0]
    assert float(path.read_text()) == 102.0
