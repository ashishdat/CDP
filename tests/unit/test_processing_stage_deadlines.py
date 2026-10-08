import sys
import pytest
from scripts.run_hackathon_1000_cascade import _processing_stage_timeout, _run_stage, _ocr_pool_enabled


def test_ocr_timeout_is_distinct_and_process_is_terminated(tmp_path):
    code, reason = _run_stage([sys.executable, "-c", "import time; time.sleep(30)"],
                             tmp_path / "ocr.log", timeout=.2, stage_label="OCR")
    assert code == 124
    assert reason == "OCR_TIMEOUT:0.2"


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "1801"])
def test_invalid_budget_cannot_disable_stage_deadline(monkeypatch, value):
    monkeypatch.setenv("CDP_OCR_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError):
        _processing_stage_timeout("ocr")


def test_shared_pool_cannot_bypass_owned_process_deadline(monkeypatch):
    monkeypatch.setenv("CDP_OCR_WORKER_POOL", "1")
    assert not _ocr_pool_enabled()
