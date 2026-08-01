from typing import ClassVar

from PIL import Image

from workers.ppocr_v5.adapter import PPOCRv5Adapter


class FakeResult:
    json: ClassVar = {
        "res": {"rec_texts": ["Jane Doe", ""], "rec_scores": [0.93, 0.2]}
    }


class FakePipeline:
    def predict(self, image):
        assert image.shape == (10, 20, 3)
        return [FakeResult()]


def test_ppocr_v5_parses_v3_prediction_contract():
    lines = PPOCRv5Adapter(pipeline=FakePipeline()).recognize(
        Image.new("RGB", (20, 10))
    )
    assert [(line.text, line.confidence) for line in lines] == [("Jane Doe", 0.93)]
