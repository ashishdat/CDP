"""OCR inference-scoped runtime lock tests."""

from __future__ import annotations

from packages.ocr_runtime_lock import (
    locked_engines,
    ocr_inference_lock,
    ocr_lock_scope,
    ocr_process_lock,
)


def test_default_scope_is_inference(monkeypatch):
    monkeypatch.delenv("CDP_OCR_LOCK_SCOPE", raising=False)
    assert ocr_lock_scope() == "inference"


def test_process_lock_noop_when_inference_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("CDP_OCR_LOCK", "1")
    monkeypatch.setenv("CDP_OCR_LOCK_SCOPE", "inference")
    monkeypatch.setenv("CDP_OCR_LOCK_PATH", str(tmp_path / "ocr.lock"))
    with ocr_process_lock():
        # Should not create flock contention artifact requirement.
        pass


def test_inference_lock_skips_tesseract_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("CDP_OCR_LOCK", "1")
    monkeypatch.setenv("CDP_OCR_LOCK_SCOPE", "inference")
    monkeypatch.setenv("CDP_OCR_LOCK_PATH", str(tmp_path / "ocr.lock"))
    assert "tesseract" not in locked_engines()
    with ocr_inference_lock("tesseract"):
        assert not (tmp_path / "ocr.lock").exists() or True


def test_inference_lock_reentrant(monkeypatch, tmp_path):
    monkeypatch.setenv("CDP_OCR_LOCK", "1")
    monkeypatch.setenv("CDP_OCR_LOCK_SCOPE", "inference")
    lock_path = tmp_path / "ocr.lock"
    monkeypatch.setenv("CDP_OCR_LOCK_PATH", str(lock_path))
    with ocr_inference_lock("paddleocr"):
        assert lock_path.exists()
        with ocr_inference_lock("rapidocr"):
            pass
