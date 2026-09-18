"""Phase 3: lazy, regional OCR escalation with caller-owned acceptance policy."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from time import perf_counter_ns

from PIL import Image

from packages.extraction_pipeline.models import FeatureFlag
from packages.extraction_pipeline.registry import StageRegistration
from packages.ocr_contracts import ModelNotAvailableError, TextLine

ENGINE_ORDER = ("rapidocr", "paddleocr", "tesseract", "trocr")

_ENGINE_FACTORIES: Mapping[str, Callable[[], "Recognizer"]] | None = None


def configure_ocr_engine_factories(
    factories: Mapping[str, Callable[[], "Recognizer"]],
) -> None:
    """Composition root registers concrete OCR engine factories."""
    global _ENGINE_FACTORIES
    _ENGINE_FACTORIES = dict(factories)


def default_ocr_factories() -> Mapping[str, Callable[[], "Recognizer"]]:
    if _ENGINE_FACTORIES is None:
        raise RuntimeError(
            "OCR engine factories not configured; "
            "call configure_ocr_engine_factories from composition root"
        )
    return _ENGINE_FACTORIES


@dataclass(frozen=True)
class OCRRouteRequest:
    image: Image.Image
    bbox: tuple[int, int, int, int]
    allow_handwriting: bool = False
    # Optional per-call engine ladder (e.g. governed field-route primary→confirm).
    # When omitted, ENGINE_ORDER is used. Unknown names are rejected.
    engine_order: tuple[str, ...] | None = None
    # Stop after this many usable observations once one is accepted.
    # None → legacy dual-confirm (2 when order has ≥2 engines).
    min_usable: int | None = None

    def __post_init__(self):
        box = tuple(self.bbox)
        if len(box) != 4 or any(type(value) is not int for value in box):
            raise ValueError("OCR region must contain four integer coordinates")
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= self.image.width and 0 <= y0 < y1 <= self.image.height):
            raise ValueError("OCR region must be inside the source image")
        if type(self.allow_handwriting) is not bool:
            raise ValueError("Handwriting eligibility must be explicit")
        object.__setattr__(self, "bbox", box)
        if self.engine_order is not None:
            order = tuple(self.engine_order)
            if not order or any(type(name) is not str for name in order):
                raise ValueError("engine_order must be a non-empty tuple of engine names")
            unknown = set(order) - set(ENGINE_ORDER)
            if unknown:
                raise ValueError(f"Unknown engines in engine_order: {sorted(unknown)}")
            object.__setattr__(self, "engine_order", order)
        if self.min_usable is not None and (
            type(self.min_usable) is not int or self.min_usable < 1
        ):
            raise ValueError("min_usable must be a positive int")


@dataclass(frozen=True)
class OCRObservation:
    lines: tuple[TextLine, ...]
    insufficient_evidence: bool = False

    def __post_init__(self):
        object.__setattr__(self, "lines", tuple(self.lines))


@dataclass(frozen=True)
class OCRAttempt:
    engine: str
    observation: OCRObservation | None
    latency_ns: int
    reason: str


@dataclass(frozen=True)
class OCRRoutingResult:
    selected: OCRAttempt | None
    attempts: tuple[OCRAttempt, ...]
    reason: str


Recognizer = Callable[[OCRRouteRequest], OCRObservation]


class OCRRouter:
    """Invoke RapidOCR -> Paddle -> Tesseract -> eligible TrOCR only as needed.

    Acceptance is supplied by the caller; this module adds no confidence or
    business-rule thresholds. Models are lazily constructed and reused. One
    router serializes calls because existing model adapters are stateful.
    Unexpected engine/policy exceptions propagate without retry or escalation.

    Engine factories must be injected via ``factories=`` or registered with
    ``configure_ocr_engine_factories`` from a composition root (workers).
    """

    def __init__(
        self,
        accept: Callable[[OCRAttempt], bool],
        *,
        factories: Mapping[str, Callable[[], Recognizer]] | None = None,
        clock: Callable[[], int] = perf_counter_ns,
    ):
        if not callable(accept):
            raise ValueError("An acceptance policy is required")
        self._factories = (
            dict(factories) if factories is not None else dict(default_ocr_factories())
        )
        if set(self._factories) != set(ENGINE_ORDER) or not all(
            callable(factory) for factory in self._factories.values()
        ):
            raise ValueError("Exactly the four ordered engine factories are required")
        self._recognizers: dict[str, Recognizer] = {}
        self._accept = accept
        self._clock = clock
        self._lock = Lock()

    def route(self, request: OCRRouteRequest) -> OCRRoutingResult:
        # The caller may have resized the mutable image after request creation.
        OCRRouteRequest(
            request.image,
            request.bbox,
            request.allow_handwriting,
            request.engine_order,
            request.min_usable,
        )
        order = request.engine_order or ENGINE_ORDER
        # Governed routes list primary then confirmation. Legacy default requires
        # two usable observations (E2). SELECTIVE_E2_ONLY callers pass min_usable=1
        # so a field-shaped primary can stop without invoking Paddle/Rapid twice.
        if request.min_usable is not None:
            required_usable = request.min_usable
        else:
            required_usable = 2 if len(tuple(order)) >= 2 else 1
        with self._lock:
            attempts = []
            usable_count = 0
            first_accepted: OCRAttempt | None = None
            for engine in order:
                if engine == "trocr" and not request.allow_handwriting:
                    continue
                started = self._clock()
                try:
                    if engine not in self._recognizers:
                        self._recognizers[engine] = self._factories[engine]()
                    observation = self._recognizers[engine](request)
                except ModelNotAvailableError:
                    attempts.append(
                        OCRAttempt(engine, None, self._clock() - started, "UNAVAILABLE")
                    )
                    continue
                attempt = OCRAttempt(engine, observation, self._clock() - started, "OBSERVED")
                attempts.append(attempt)
                usable = not observation.insufficient_evidence and any(
                    line.text.strip() for line in observation.lines
                )
                if not usable:
                    continue
                usable_count += 1
                if self._accept(attempt) and first_accepted is None:
                    first_accepted = attempt
                if first_accepted is not None and usable_count >= required_usable:
                    return OCRRoutingResult(
                        first_accepted, tuple(attempts), "POLICY_SATISFIED"
                    )
            if first_accepted is not None:
                # Single usable engine (others unavailable) still satisfies policy.
                return OCRRoutingResult(
                    first_accepted, tuple(attempts), "POLICY_SATISFIED"
                )
            return OCRRoutingResult(None, tuple(attempts), "EXHAUSTED")

    def stage(self, legacy):
        def replacement(payload, context):
            return self.route(payload)

        return StageRegistration("ocr_router", legacy, replacement, FeatureFlag.OCR_ROUTER_V3)
