from PIL import Image

from workers.cascade.engine_independence import independence_group
from workers.cascade.got_ocr2_adapter import GOTOCR2Adapter


class Tensor:
    shape = (1, 2)

    def to(self, device):
        return self


class Sequence:
    def __getitem__(self, key):
        return self


class Processor:
    tokenizer = object()

    def __call__(self, image, return_tensors):
        return {"input_ids": Tensor(), "pixel_values": Tensor()}

    def batch_decode(self, sequence, skip_special_tokens):
        return ["HELLO"]


class Generated:
    def __init__(self):
        self.sequences = Sequence()
        self.scores = []


class Model:
    generate_kwargs = None

    def to(self, device):
        return self

    def eval(self):
        return self

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return Generated()


def test_got_ocr_candidate_abstains_without_confidence() -> None:
    model = Model()
    result = GOTOCR2Adapter(processor=Processor(), model=model, max_new_tokens=42).recognize(
        Image.new("RGB", (40, 20), "white")
    )
    assert result.text == "HELLO"
    assert result.insufficient_evidence
    assert model.generate_kwargs["max_new_tokens"] == 42
    assert model.generate_kwargs["stop_strings"] == "<|im_end|>"


def test_got_ocr_has_independent_architecture_group() -> None:
    assert independence_group("got-ocr2") == "GOT_OCR_FAMILY"
