from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from packages.ocr_router import (
    ENGINE_ORDER,
    OCRObservation,
    OCRRouter,
    OCRRouteRequest,
)
from workers.page_detection.text_extraction import ModelNotAvailableError, TextLine


def request(handwriting=False):
    return OCRRouteRequest(Image.new("L", (30, 20), 255), (5, 3, 25, 15), handwriting)


def observation(text=" raw OCR "):
    return OCRObservation((TextLine(text, 5, 3, 25, 15, 0.8),))


def factories(events, outputs):
    def factory(name):
        def construct():
            events.append(("construct", name))

            def recognize(payload):
                events.append(("recognize", name))
                result = outputs.get(name, observation())
                if isinstance(result, Exception):
                    raise result
                return result

            return recognize

        return construct

    return {name: factory(name) for name in reversed(ENGINE_ORDER)}


@pytest.mark.parametrize("winner", ENGINE_ORDER)
def test_order_lazy_construction_stop_and_original_observation_identity(winner):
    events = []
    outputs = {name: observation(name) for name in ENGINE_ORDER}
    router = OCRRouter(
        lambda attempt: attempt.engine == winner, factories=factories(events, outputs)
    )
    assert events == []
    result = router.route(request(True))
    expected = ENGINE_ORDER[: ENGINE_ORDER.index(winner) + 1]
    assert [name for action, name in events if action == "recognize"] == list(expected)
    assert [attempt.engine for attempt in result.attempts] == list(expected)
    assert result.selected is result.attempts[-1]
    for attempt in result.attempts:
        assert attempt.observation is outputs[attempt.engine]


def test_disabled_handwriting_is_never_constructed_or_executed():
    events = []
    result = OCRRouter(lambda _: False, factories=factories(events, {})).route(request())
    assert result.selected is None
    assert result.reason == "EXHAUSTED"
    assert len(result.attempts) == 3
    assert all(name != "trocr" for _, name in events)


def test_blank_and_insufficient_observations_are_preserved_but_not_accepted():
    events, accepted = [], []
    blank = observation("   ")
    insufficient = OCRObservation(observation().lines, True)
    outputs = {"rapidocr": blank, "paddleocr": insufficient}

    def accept(attempt):
        accepted.append(attempt.engine)
        return True

    result = OCRRouter(accept, factories=factories(events, outputs)).route(request())
    assert result.attempts[0].observation is blank
    assert result.attempts[1].observation is insufficient
    assert accepted == ["tesseract"]


def test_unavailable_engine_falls_through_without_retry():
    events = []
    outputs = {"rapidocr": ModelNotAvailableError("optional dependency")}
    result = OCRRouter(lambda _: True, factories=factories(events, outputs)).route(request())
    assert result.attempts[0].reason == "UNAVAILABLE"
    assert result.attempts[0].observation is None
    assert result.selected.engine == "paddleocr"
    assert events.count(("recognize", "rapidocr")) == 1


def test_unexpected_engine_exception_propagates_unchanged():
    error = RuntimeError("engine failure")
    events = []
    router = OCRRouter(lambda _: True, factories=factories(events, {"rapidocr": error}))
    with pytest.raises(RuntimeError) as caught:
        router.route(request(True))
    assert caught.value is error
    assert events == [("construct", "rapidocr"), ("recognize", "rapidocr")]


def test_policy_exception_does_not_trigger_fallback():
    error = ValueError("policy failure")
    events = []

    def accept(attempt):
        raise error

    router = OCRRouter(accept, factories=factories(events, {}))
    with pytest.raises(ValueError) as caught:
        router.route(request(True))
    assert caught.value is error
    assert len(events) == 2


def test_models_reused_but_no_cross_request_result_cache():
    events = []
    router = OCRRouter(lambda _: True, factories=factories(events, {}))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(router.route, [request() for _ in range(8)]))
    assert events.count(("construct", "rapidocr")) == 1
    assert events.count(("recognize", "rapidocr")) == 8
    assert len({id(result.attempts) for result in results}) == 8


def test_timings_include_factory_and_inference():
    ticks = iter((10, 40))
    router = OCRRouter(lambda _: True, factories=factories([], {}), clock=lambda: next(ticks))
    assert router.route(request()).selected.latency_ns == 30


@pytest.mark.parametrize(
    "bbox", [(-1, 0, 10, 10), (0, 0, 31, 10), (0, 0, 0, 1), (0, 0, 1.5, 2), (0, 1)]
)
def test_invalid_regions_rejected(bbox):
    with pytest.raises(ValueError):
        OCRRouteRequest(Image.new("L", (30, 20)), bbox)


def test_invalid_factory_configuration_is_not_silently_reordered_or_skipped():
    with pytest.raises(ValueError):
        OCRRouter(lambda _: True, factories={})


def test_factory_mapping_is_snapshotted():
    supplied = factories([], {})
    router = OCRRouter(lambda _: True, factories=supplied)
    supplied.clear()
    assert router.route(request()).selected.engine == "rapidocr"
