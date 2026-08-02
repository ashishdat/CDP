"""`PaddleOCRTextExtractor.extract_region`'s crop/upscale/coordinate math --
tested with a fake OCR engine stub since `paddleocr` isn't installed on
every dev host (no wheel for this project's Python version; see the
module's own docstring)."""

import numpy as np
from PIL import Image

from workers.page_detection.text_extraction import PaddleOCRTextExtractor
from workers.retry.alternate_preprocessing import UPSCALE_FACTOR


class _FakeEngine:
    """Scripted stand-in for `paddleocr.PaddleOCR`: returns one box that
    spans the whole (upscaled) crop it's given, so the test can assert the
    box's origin/size land back in the pre-upscale, page-relative frame."""

    def __init__(self) -> None:
        self.last_shape: tuple[int, int] | None = None
        self.last_cls: bool | None = None

    def ocr(self, arr: np.ndarray, cls: bool = True):
        self.last_cls = cls
        h, w = arr.shape[0], arr.shape[1]
        self.last_shape = (w, h)
        box = [[0, 0], [w, 0], [w, h], [0, h]]
        return [[(box, ("42", 0.77))]]


def _extractor(engine: _FakeEngine) -> PaddleOCRTextExtractor:
    extractor = object.__new__(PaddleOCRTextExtractor)
    extractor._engine = engine
    extractor._max_full_page_side = 1600
    return extractor


def test_extract_region_upscales_the_crop_before_ocr():
    engine = _FakeEngine()
    extractor = _extractor(engine)
    image = Image.new("L", (400, 400), color=255)

    extractor.extract_region(image, 100, 100, 150, 130)

    assert engine.last_shape == (int(50 * UPSCALE_FACTOR), int(30 * UPSCALE_FACTOR))


def test_extract_region_returns_boxes_in_original_page_coordinates():
    engine = _FakeEngine()
    extractor = _extractor(engine)
    image = Image.new("L", (400, 400), color=255)

    [line] = extractor.extract_region(image, 100, 100, 150, 130)

    assert line.text == "42"
    assert line.confidence == 0.77
    assert (line.x0, line.y0) == (100.0, 100.0)
    assert (line.x1, line.y1) == (150.0, 130.0)


def test_full_page_ocr_is_bounded_and_maps_boxes_back_to_source_coordinates():
    engine = _FakeEngine()
    extractor = _extractor(engine)
    image = Image.new("L", (2400, 3200), color=255)

    [line] = extractor.extract(image)

    assert engine.last_shape == (1200, 1600)
    assert engine.last_cls is False
    assert (line.x0, line.y0) == (0.0, 0.0)
    assert (line.x1, line.y1) == (2400.0, 3200.0)
