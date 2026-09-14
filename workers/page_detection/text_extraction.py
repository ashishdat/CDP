"""OCR text extraction interface.

`paddlepaddle` (PaddleOCR's backend) has no wheel for every dev
environment (confirmed: no match for Python 3.14 on this project's host --
see docs/DATASET_FINDINGS.md-adjacent notes in docs/ARCHITECTURE.md §12),
so the real OCR engine is imported lazily and only inside the Docker image
that installs the `[ml]` extras group (Python 3.11). Everything in
`workers.page_detection`/`workers.standard_form_extraction` depends on the
`TextExtractor` protocol below, never on `paddleocr` directly, so routing
and field-processor logic is fully unit-testable with a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


class TextExtractor(Protocol):
    def extract(self, image: Image.Image) -> list[TextLine]:
        """Full-page OCR, used for anchor-phrase verification."""
        ...

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        """Regional OCR, used by standard_form_extraction on aligned pages."""
        ...


class ModelNotAvailableError(RuntimeError):
    pass


class RapidOCRTextExtractor:
    """RapidOCR adapter restricted to explicitly supplied field regions.

    Applies Phase 8.10 field-profile crop preparation when field context is set,
    and permits one bounded alternate-profile OCR attempt on empty reads.
    """

    engine_name = "rapidocr"
    model_name = "RapidOCR-ONNX"
    preprocessing_version = "2.0-phase8.10-evaluation"

    def __init__(
        self,
        backend=None,
        model_version: str = "rapidocr-onnxruntime",
        *,
        intra_op_num_threads: int | None = None,
        inter_op_num_threads: int | None = None,
        preprocessing_registry=None,
        enable_ocr_recovery: bool = True,
    ) -> None:
        self._engine = backend
        self._regional_upscale = backend is None
        self._initialization_count = 1 if backend is not None else 0
        self._intra_op_num_threads = intra_op_num_threads
        self._inter_op_num_threads = inter_op_num_threads
        self.last_profile: dict[str, float | str] = {}
        self.model_version = model_version
        self._context: dict[str, object] = {}
        self._preprocessing = preprocessing_registry
        self._enable_ocr_recovery = enable_ocr_recovery
        self.last_preprocessing_profile = "REGIONAL_DEFAULT"

    def set_context(self, **values) -> None:
        self._context.update(values)

    def _registry(self):
        if self._preprocessing is None:
            from pathlib import Path

            from packages.ocr.preprocessing import PreprocessingRegistry

            config = Path(__file__).resolve().parents[2] / "config" / "ocr_preprocessing_phase8_10.yaml"
            self._preprocessing = PreprocessingRegistry.load(config)
        return self._preprocessing

    @property
    def initialization_count(self) -> int:
        return self._initialization_count

    def _load(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise ModelNotAvailableError(
                    "rapidocr-onnxruntime is not installed -- install the '[ocr]' extra"
                ) from exc
            kwargs = {}
            if self._intra_op_num_threads is not None:
                kwargs["intra_op_num_threads"] = self._intra_op_num_threads
            if self._inter_op_num_threads is not None:
                kwargs["inter_op_num_threads"] = self._inter_op_num_threads
            self._engine = RapidOCR(**kwargs)
            self._initialization_count += 1
        return self._engine

    def extract(self, image: Image.Image) -> list[TextLine]:
        raise ValueError("RapidOCR primary is region-only for supported standard forms")

    def _prepare_crop(self, crop: Image.Image, *, profile_override: str | None = None):
        field = str(self._context.get("field") or self._context.get("field_name") or "")
        field_type = str(self._context.get("field_type") or self._context.get("datatype") or "text")
        if not field and profile_override is None:
            return crop, "REGIONAL_DEFAULT", False
        registry = self._registry()
        applied = registry.apply(crop, field or "unknown", field_type, requested=profile_override)
        profile_steps = registry.config["profiles"][applied.profile]
        return applied.image.convert("RGB"), applied.profile, "upscale_2x" in profile_steps

    def _recognize(self, working: Image.Image, *, scale: float, x0: int, y0: int) -> list[TextLine]:
        import numpy as np

        raw = self._load()(np.asarray(working.convert("RGB")))
        elapsed = raw[1] if isinstance(raw, tuple) and len(raw) > 1 else None
        elapsed_parts = elapsed if isinstance(elapsed, (list, tuple)) else ()
        rows = raw[0] if isinstance(raw, tuple) else raw
        lines: list[TextLine] = []
        for row in rows or []:
            if len(row) < 3:
                continue
            box, text, confidence = row[0], str(row[1]), float(row[2])
            xs, ys = [point[0] for point in box], [point[1] for point in box]
            lines.append(
                TextLine(
                    text,
                    min(xs) / scale + x0,
                    min(ys) / scale + y0,
                    max(xs) / scale + x0,
                    max(ys) / scale + y0,
                    confidence,
                )
            )
        self.last_profile.update(
            {
                "detector": (elapsed_parts[0] * 1000 if len(elapsed_parts) > 0 else 0.0),
                "classifier": (elapsed_parts[1] * 1000 if len(elapsed_parts) > 1 else 0.0),
                "recognizer": (elapsed_parts[2] * 1000 if len(elapsed_parts) > 2 else 0.0),
            }
        )
        return lines

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        import time

        started = time.perf_counter()
        crop = image.crop((x0, y0, x1, y1)).convert("RGB")
        crop_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        prepared, profile, profile_upscaled = self._prepare_crop(crop)
        prep_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        # Avoid stacking blind 3x upscale on profiles that already upscale.
        scale = 1
        if self._regional_upscale and not profile_upscaled and max(prepared.size) < 900:
            scale = 3
        working = (
            prepared
            if scale == 1
            else prepared.resize(
                (prepared.width * scale, prepared.height * scale), Image.Resampling.LANCZOS
            )
        )
        resize_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        lines = self._recognize(working, scale=float(scale), x0=x0, y0=y0)
        engine_ms = (time.perf_counter() - started) * 1000
        joined = " ".join(line.text for line in lines).strip()
        recovery_profile = None

        if self._enable_ocr_recovery and not joined:
            from packages.recovery import decide_ocr_recovery

            decision = decide_ocr_recovery(primary_profile=profile, primary_text=joined)
            if decision.attempt_alternate and decision.alternate_profile:
                started = time.perf_counter()
                alt_crop, recovery_profile, alt_upscaled = self._prepare_crop(
                    crop, profile_override=decision.alternate_profile
                )
                alt_scale = 1
                if self._regional_upscale and not alt_upscaled and max(alt_crop.size) < 900:
                    alt_scale = 3
                alt_working = (
                    alt_crop
                    if alt_scale == 1
                    else alt_crop.resize(
                        (alt_crop.width * alt_scale, alt_crop.height * alt_scale),
                        Image.Resampling.LANCZOS,
                    )
                )
                alt_lines = self._recognize(alt_working, scale=float(alt_scale), x0=x0, y0=y0)
                self.last_profile["ocr_recovery_ms"] = (time.perf_counter() - started) * 1000
                if any(line.text.strip() for line in alt_lines):
                    lines = alt_lines
                    profile = recovery_profile or profile

        self.last_preprocessing_profile = profile
        self.last_profile.update(
            {
                "image_crop_convert": crop_ms,
                "field_profile_preprocessing": prep_ms,
                "resize_preprocessing": resize_ms,
                "rapidocr_engine_wall": engine_ms,
                "preprocessing_profile": profile,
                "ocr_recovery_profile": recovery_profile or "",
            }
        )
        return lines


class RapidOCRFullPageTextExtractor(RapidOCRTextExtractor):
    """RapidOCR detector/recognizer for unknown layouts only.

    Known templates continue using ``RapidOCRTextExtractor`` region calls;
    exposing full-page OCR as a separate type prevents accidental expansion
    of the standard-form cost envelope.
    """

    engine_name = "rapidocr_full_page"

    def __init__(self, backend=None, model_version: str = "rapidocr-onnxruntime",
                 max_full_page_side: int = 2000, *,
                 intra_op_num_threads: int | None = None,
                 inter_op_num_threads: int | None = None) -> None:
        super().__init__(backend=backend, model_version=model_version,
                         intra_op_num_threads=intra_op_num_threads,
                         inter_op_num_threads=inter_op_num_threads)
        self._max_full_page_side = max_full_page_side

    def extract(self, image: Image.Image) -> list[TextLine]:
        import time

        started = time.perf_counter()
        longest = max(image.size)
        scale = min(1.0, self._max_full_page_side / longest)
        working = image if scale == 1 else image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
        full_page_resize_ms = (time.perf_counter() - started) * 1000
        lines = super().extract_region(working, 0, 0, working.width, working.height)
        self.last_profile["full_page_resize"] = full_page_resize_ms
        if scale == 1:
            return lines
        return [TextLine(line.text, line.x0 / scale, line.y0 / scale,
                         line.x1 / scale, line.y1 / scale, line.confidence)
                for line in lines]


class PaddleOCRTextExtractor:
    """Real adapter. Constructed lazily -- importing `paddleocr` at class
    definition time would make every caller of this module (including
    pure-logic unit tests) require the `[ml]` extras group installed."""

    def __init__(
        self,
        lang: str = "en",
        model_name: str = "PP-OCRv4",
        model_version: str = "paddleocr-2.x",
        cpu_threads: int = 2,
        max_full_page_side: int = 1600,
    ) -> None:
        self._lang = lang
        self._model_name = model_name
        self._model_version = model_version
        self._cpu_threads = cpu_threads
        self._max_full_page_side = max_full_page_side
        self._engine = None

    @property
    def engine_name(self) -> str:
        return "paddleocr"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ModelNotAvailableError(
                "paddleocr is not installed -- install the '[ml]' extras group "
                "(see pyproject.toml) or run inside the ML-enabled worker image"
            ) from exc
        self._engine = PaddleOCR(
            # Preparation already normalizes page orientation. Loading the
            # separate angle-classifier model duplicates work and materially
            # increases the CPU worker's cold-start memory.
            use_angle_cls=False,
            lang=self._lang,
            show_log=False,
            ocr_version=self._model_name,
            enable_mkldnn=False,
            cpu_threads=self._cpu_threads,
        )
        return self._engine

    def extract(self, image: Image.Image) -> list[TextLine]:
        # Routing needs anchor text, not full-resolution glyph geometry.
        # Bounding the longest side prevents full-page scans from creating
        # multi-gigabyte detector feature maps. Returned boxes are mapped
        # back into source-page coordinates.
        longest_side = max(image.size)
        if longest_side <= self._max_full_page_side:
            return self._run(image)
        scale = self._max_full_page_side / longest_side
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        lines = self._run(resized)
        return [
            TextLine(
                line.text,
                line.x0 / scale,
                line.y0 / scale,
                line.x1 / scale,
                line.y1 / scale,
                line.confidence,
            )
            for line in lines
        ]

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        # Regional crops are the majority of OCR calls in this pipeline and
        # are cheap to upscale individually (same cost reasoning as
        # workers.retry.alternate_preprocessing's crop-scoped presets); the
        # source scans are ~200 DPI, below the ~300 DPI most OCR engines are
        # tuned for, so a modest upscale here measurably helps small-field
        # recognition. Whole-page `extract()` deliberately stays untouched --
        # that path is cost-sensitive (tests/performance/test_throughput.py).
        # Imported lazily -- `workers.retry` imports this module too
        # (retry_service depends on TextExtractor/TextLine), so a top-level
        # import here would deadlock on the circular package init.
        from workers.retry.alternate_preprocessing import UPSCALE_FACTOR, upscale

        crop = image.crop((x0, y0, x1, y1))
        upscaled = upscale(crop, UPSCALE_FACTOR)
        lines = self._run(upscaled)
        # undo the upscale, then translate crop-local coordinates back into
        # page coordinates
        return [
            TextLine(
                l.text,
                l.x0 / UPSCALE_FACTOR + x0,
                l.y0 / UPSCALE_FACTOR + y0,
                l.x1 / UPSCALE_FACTOR + x0,
                l.y1 / UPSCALE_FACTOR + y0,
                l.confidence,
            )
            for l in lines
        ]

    def _run(self, image: Image.Image) -> list[TextLine]:
        import numpy as np

        result = self._load().ocr(np.array(image.convert("RGB")), cls=False)
        lines: list[TextLine] = []
        for page in result or []:
            for box, (text, confidence) in page or []:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                lines.append(TextLine(text, min(xs), min(ys), max(xs), max(ys), float(confidence)))
        return lines
