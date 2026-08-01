from PIL import Image, ImageDraw

from evaluation.benchmark_constrained_state import VALID_STATES, variants


def test_state_contract_is_constrained_and_preprocessing_preserves_source() -> None:
    source = Image.new("L", (100, 40), 255)
    ImageDraw.Draw(source).line((0, 39, 99, 39), fill=0, width=1)
    generated = variants(source)
    assert set(generated) == {
        "gray_4x", "contrast_4x", "threshold_4x", "median_threshold_4x"
    }
    assert source.size == (100, 40)
    assert {"AZ", "LA", "NY", "DC"}.issubset(VALID_STATES)
