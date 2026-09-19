"""Unit tests for isolated PP-OCRv5 Server subprocess bridge."""

from PIL import Image

from packages.ocr.independence import independence_group
from workers.ppocr_v5.subprocess_bridge import ppocr_v5_server_enabled


def test_ppocr_v5_server_maps_to_paddle_family():
    assert independence_group("ppocr_v5_server") == "PADDLE_FAMILY"
    assert independence_group("PP-OCRv5_server") == "PADDLE_FAMILY"


def test_ppocr_v5_server_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CDP_PPOCRV5_SERVER", raising=False)
    assert ppocr_v5_server_enabled() is False
    monkeypatch.setenv("CDP_PPOCRV5_SERVER", "1")
    assert ppocr_v5_server_enabled() is True


def test_ppocr_v5_adapter_server_flag_parses_fake_pipeline():
    from typing import ClassVar

    from workers.ppocr_v5.adapter import PPOCRv5Adapter

    class FakeResult:
        json: ClassVar = {"res": {"rec_texts": ["26.00"], "rec_scores": [0.99]}}

    class FakePipeline:
        def predict(self, image):
            return [FakeResult()]

    lines = PPOCRv5Adapter(pipeline=FakePipeline(), server=True).recognize(
        Image.new("RGB", (40, 20))
    )
    assert lines[0].text == "26.00"
