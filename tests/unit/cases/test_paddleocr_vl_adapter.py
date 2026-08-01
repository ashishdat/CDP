from PIL import Image

from workers.cascade.paddleocr_vl_adapter import PaddleOCRVLAdapter


class Inputs(dict):
    def to(self, device):
        return self


class Processor:
    def apply_chat_template(self, *args, **kwargs):
        return Inputs(input_ids=type("Ids", (), {"shape": (1, 3)})())

    def batch_decode(self, *args, **kwargs):
        return ["AZ"]


class Output:
    def __getitem__(self, key):
        return self


class Model:
    def generate(self, **kwargs):
        return Output()


def test_paddleocr_vl_regional_ocr() -> None:
    result = PaddleOCRVLAdapter(processor=Processor(), model=Model()).recognize(
        Image.new("RGB", (20, 20), "white")
    )
    assert result.text == "AZ"
    assert not result.insufficient_evidence
