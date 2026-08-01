from PIL import Image

from workers.cascade.engine_independence import independence_group
from workers.cascade.florence2_adapter import Florence2Adapter


class Inputs(dict):
    pass


class Tensor:
    def to(self, device):
        return self


class Processor:
    def __call__(self, **kwargs):
        return Inputs(input_ids=Tensor(), pixel_values=Tensor(), attention_mask=Tensor())

    def batch_decode(self, sequences, skip_special_tokens=False):
        return ["<OCR>HELLO"]

    def post_process_generation(self, decoded, task, image_size):
        return {"<OCR>": "HELLO"}


class Generated:
    def __init__(self):
        self.sequences = [[1]]
        self.scores = []


class Model:
    def to(self, device):
        return self

    def eval(self):
        return self

    def generate(self, **kwargs):
        return Generated()


def test_florence_candidate_abstains_without_calibrated_confidence() -> None:
    adapter = Florence2Adapter(processor=Processor(), model=Model())
    result = adapter.recognize(Image.new("RGB", (40, 20), "white"))
    assert result.text == "HELLO"
    assert result.insufficient_evidence
    assert result.confidence == 0.0


def test_florence_is_an_independent_architecture_group() -> None:
    assert independence_group("florence2-base") == "FLORENCE_FAMILY"
