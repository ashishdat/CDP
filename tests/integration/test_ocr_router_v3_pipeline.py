import pytest
from PIL import Image

from packages.extraction_pipeline import (
    ExtractionPipeline,
    FeatureFlag,
    FeatureFlags,
    PipelineContext,
    StageRegistry,
)
from packages.ocr_router import ENGINE_ORDER, OCRObservation, OCRRouter, OCRRouteRequest
from workers.page_detection.text_extraction import TextLine


@pytest.mark.parametrize(
    "pipeline_enabled,ocr_enabled", [(False, False), (False, True), (True, False), (True, True)]
)
def test_pipeline_flag_rollback_preserves_legacy_identity(pipeline_enabled, ocr_enabled):
    invoked = []
    legacy_result = object()
    payload = OCRRouteRequest(Image.new("L", (10, 10)), (0, 0, 10, 10))

    def legacy(value, context):
        assert value is payload
        invoked.append("legacy")
        return legacy_result

    def factory():
        invoked.append("ocr")
        return lambda value: OCRObservation((TextLine("raw", 0, 0, 10, 10, 0.9),))

    router = OCRRouter(lambda _: True, factories={name: factory for name in ENGINE_ORDER})
    pipeline = ExtractionPipeline(StageRegistry((router.stage(legacy),)), legacy)
    flags = set()
    if pipeline_enabled:
        flags.add(FeatureFlag.PIPELINE_V3)
    if ocr_enabled:
        flags.add(FeatureFlag.OCR_ROUTER_V3)
    result = pipeline.run(payload, PipelineContext("ocr-test", FeatureFlags(flags)))
    if pipeline_enabled and ocr_enabled:
        # Confirmation cascade constructs primary + confirmation factories.
        assert invoked == ["ocr", "ocr"]
        assert result.value.selected.engine == "rapidocr"
        assert [a.engine for a in result.value.attempts] == ["rapidocr", "paddleocr"]
    else:
        assert invoked == ["legacy"]
        assert result.value is legacy_result


def test_default_regional_factories_call_existing_adapters(monkeypatch):
    from workers.cascade import tesseract_adapter
    from workers.page_detection import text_extraction

    events = []
    line = TextLine(" untouched ", 2, 3, 8, 9, 0.8)

    def adapter(name):
        class Extractor:
            def extract_region(self, image, *bbox):
                events.append((name, image, bbox))
                return [line]

        return Extractor

    monkeypatch.setattr(text_extraction, "RapidOCRTextExtractor", adapter("rapidocr"))
    monkeypatch.setattr(text_extraction, "PaddleOCRTextExtractor", adapter("paddleocr"))
    monkeypatch.setattr(tesseract_adapter, "TesseractTextExtractor", adapter("tesseract"))
    image = Image.new("L", (10, 10))
    result = OCRRouter(lambda a: a.engine == "tesseract").route(
        OCRRouteRequest(image, (2, 3, 8, 9))
    )
    assert [event[0] for event in events] == list(ENGINE_ORDER[:3])
    assert all(event[1] is image and event[2] == (2, 3, 8, 9) for event in events)
    assert all(attempt.observation.lines[0] is line for attempt in result.attempts)


def test_trocr_bridge_crops_once_and_respects_insufficient_evidence(monkeypatch):
    from workers.unstructured_extraction import trocr_adapter

    seen = []

    class Adapter:
        def recognize(self, crop):
            seen.append(crop.size)
            return trocr_adapter.TrOCRResult(" handwritten ", 0.4, True)

    monkeypatch.setattr(trocr_adapter, "TrOCRAdapter", Adapter)
    from packages.ocr_router import _handwriting_factory

    factories = {name: lambda: lambda req: OCRObservation(()) for name in ENGINE_ORDER}
    factories["trocr"] = _handwriting_factory
    router = OCRRouter(lambda _: True, factories=factories)
    result = router.route(OCRRouteRequest(Image.new("L", (30, 20)), (5, 3, 25, 15), True))
    assert seen == [(20, 12)]
    assert result.selected is None
    line = result.attempts[-1].observation.lines[0]
    assert (line.text, line.x0, line.y0, line.x1, line.y1) == (" handwritten ", 5, 3, 25, 15)


@pytest.mark.parametrize("missing_dependency", [False, True])
def test_trocr_missing_dependency_is_distinct_from_inference_failure(
    monkeypatch, missing_dependency
):
    from packages.ocr_router import _handwriting_factory
    from workers.page_detection.text_extraction import ModelNotAvailableError
    from workers.unstructured_extraction import trocr_adapter

    error = RuntimeError("adapter failed")

    class Adapter:
        def recognize(self, crop):
            if missing_dependency:
                raise error from ImportError("optional dependency")
            raise error

    monkeypatch.setattr(trocr_adapter, "TrOCRAdapter", Adapter)
    recognizer = _handwriting_factory()
    request = OCRRouteRequest(Image.new("L", (5, 5)), (0, 0, 5, 5), True)
    expected = ModelNotAvailableError if missing_dependency else RuntimeError
    with pytest.raises(expected) as caught:
        recognizer(request)
    if not missing_dependency:
        assert caught.value is error


def test_missing_tesseract_executable_is_recorded_without_retry(monkeypatch):
    from packages.ocr_router import _regional_factory
    from workers.cascade import tesseract_adapter

    class Extractor:
        def extract_region(self, image, *bbox):
            raise FileNotFoundError("executable")

    monkeypatch.setattr(tesseract_adapter, "TesseractTextExtractor", Extractor)
    factories = {name: lambda: lambda req: OCRObservation(()) for name in ENGINE_ORDER}
    factories["tesseract"] = lambda: _regional_factory("tesseract")
    result = OCRRouter(lambda _: True, factories=factories).route(
        OCRRouteRequest(Image.new("L", (5, 5)), (0, 0, 5, 5))
    )
    assert result.reason == "EXHAUSTED"
    assert result.attempts[-1].reason == "UNAVAILABLE"
