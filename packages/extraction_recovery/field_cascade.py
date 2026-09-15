"""Field-semantic cascade OCR for CMS-1500 operational STP.

Replaces bolted per-field crop retries with one ordered plan:

  crop variants → route engines → span selection → semantic accept

Principles
----------
1. Acceptance is field-shaped (date / currency / name / id), not "any text".
2. Engine order comes from governed ``ocr_field_routes.yaml`` (primary then
   confirmation), not a global RapidOCR-first default.
3. Crop variants are typed (digit-band DOB, NPI-cleared charge, etc.) and
   exhausted only until a semantic accept fires.
4. Empty / contaminated financial crops stay empty — cascade never invents
   amounts. Claim-total E6 remains crop-total ∩ Σ line charges.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .span_selection import select_field_span, span_datatype_for_field

_ROUTE_PATH = Path(__file__).resolve().parents[2] / "config" / "ocr_field_routes.yaml"

# Map governed route names onto packages.ocr_router.ENGINE_ORDER ids.
_ENGINE_ALIASES = {
    "paddle": "paddleocr",
    "paddleocr": "paddleocr",
    "rapid": "rapidocr",
    "rapidocr": "rapidocr",
    "tesseract": "tesseract",
    "trocr": "trocr",
}

_DATE_SHAPE = re.compile(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$")
_CURRENCY_SHAPE = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d{2})$|^\d+\.\d{2}$")
_NAME_TOKEN = re.compile(r"[A-Z][A-Z'\-]{1,30}")
_ID_SHAPE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{4,20}$")


@dataclass(frozen=True)
class CropVariant:
    variant_id: str
    bbox: tuple[int, int, int, int]
    reason: str


@dataclass(frozen=True)
class CascadeStepResult:
    variant_id: str
    bbox: tuple[int, int, int, int]
    engines: tuple[str, ...]
    selected_value: str
    raw_value: str
    accepted: bool
    accept_reason: str
    candidates: tuple[dict, ...]
    attempts: tuple[dict, ...]
    router_reason: str


@dataclass
class CascadeResult:
    field_name: str
    bbox: tuple[int, int, int, int]
    candidates: list[dict]
    attempts: list[dict]
    router_reason: str
    status: str
    cascade_trace: list[CascadeStepResult] = field(default_factory=list)
    accepted: bool = False
    accept_reason: str = "EXHAUSTED"
    strategy_id: str = "field-cascade-v3"


RecognizeFn = Callable[
    [str, tuple[int, int, int, int], str, tuple[str, ...]],
    tuple[list[dict], list[dict], str],
]


def _clamp(bbox: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (int(v) for v in bbox)
    x0 = max(0, min(x0, width - 1))
    y0 = max(0, min(y0, height - 1))
    x1 = max(x0 + 1, min(x1, width))
    y1 = max(y0 + 1, min(y1, height))
    return (x0, y0, x1, y1)


def load_route_engines(field_name: str, route_path: Path | None = None) -> tuple[str, ...]:
    """Return (primary, confirmation, …) engines for a governed field route."""
    path = route_path or _ROUTE_PATH
    engines: list[str] = []
    if path.exists():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        route = (payload.get("ocr_routes") or {}).get(field_name) or {}
        for key in ("primary_engine", "confirmation_engine"):
            raw = route.get(key)
            if not raw:
                continue
            engine = _ENGINE_ALIASES.get(str(raw).casefold())
            if engine and engine not in engines:
                engines.append(engine)
    for engine in ("paddleocr", "rapidocr", "tesseract"):
        if engine not in engines:
            engines.append(engine)
    return tuple(engines)


def semantic_accept(field_name: str, value: str) -> tuple[bool, str]:
    """Return whether a span-selected value is field-shaped enough to stop."""
    text = (value or "").strip()
    if not text:
        return False, "EMPTY"
    name = (field_name or "").casefold()
    datatype = span_datatype_for_field(field_name, "")

    if name in {"patient_dob", "date_of_birth"} or datatype == "DATE":
        if _DATE_SHAPE.fullmatch(text):
            return True, "DATE_SHAPED"
        return False, "NOT_DATE_SHAPED"

    if name in {"total_charge", "total_charges", "charges", "charge_amount"} or datatype == "CURRENCY":
        if name in {"total_charge", "total_charges"} and text.startswith("-"):
            return False, "CURRENCY_LEADING_MINUS"
        cleaned = text.lstrip("$").replace(",", "")
        if _CURRENCY_SHAPE.fullmatch(text.lstrip("$")) or _CURRENCY_SHAPE.fullmatch(cleaned):
            if name in {"total_charge", "total_charges"} and re.fullmatch(r"[0-9]\.\d{2}", cleaned):
                return False, "CURRENCY_SUSPICIOUS_TINY"
            return True, "CURRENCY_SHAPED"
        return False, "NOT_CURRENCY_SHAPED"

    if name in {"patient_name", "insured_name"} or datatype == "PERSON_NAME":
        tokens = _NAME_TOKEN.findall(text.upper())
        stop = {"PATIENT", "INSURED", "NAME", "LAST", "FIRST", "MIDDLE", "INITIAL"}
        tokens = [t for t in tokens if t not in stop]
        if len(tokens) >= 2 or (len(tokens) == 1 and len(tokens[0]) >= 3):
            return True, "NAME_SHAPED"
        return False, "NOT_NAME_SHAPED"

    if name in {"insured_id_number", "member_id"} or datatype == "ALPHANUMERIC_ID":
        compact = text.upper().replace(" ", "")
        if _ID_SHAPE.fullmatch(compact):
            return True, "ID_SHAPED"
        return False, "NOT_ID_SHAPED"

    return True, "NON_EMPTY"


def crop_variants(
    field_name: str,
    primary: tuple[int, int, int, int],
    cell: Mapping[str, int],
    image_size: tuple[int, int],
) -> list[CropVariant]:
    """Typed crop ladder for critical CMS-1500 fields."""
    width, height = image_size
    cell_box = (int(cell["x0"]), int(cell["y0"]), int(cell["x1"]), int(cell["y1"]))
    cell_w = cell_box[2] - cell_box[0]
    cell_h = cell_box[3] - cell_box[1]
    variants: list[CropVariant] = [
        CropVariant("primary", _clamp(primary, width, height), "TEMPLATE_OR_INSET_PRIMARY"),
    ]
    name = (field_name or "").casefold()

    if name == "patient_dob":
        lower = (
            max(primary[0], cell_box[0] + 2),
            max(primary[1], cell_box[3] - max(22, int(0.38 * cell_h))),
            min(primary[2], cell_box[2] - int(0.08 * cell_w)),
            min(primary[3], cell_box[3] - 1),
        )
        variants.append(CropVariant("dob_digit_band", _clamp(lower, width, height), "DOB_DIGIT_BAND"))
        loose = (
            max(primary[0], cell_box[0] + 2),
            max(primary[1], cell_box[1] + int(0.22 * cell_h)),
            min(primary[2], cell_box[2] - int(0.08 * cell_w)),
            min(primary[3], cell_box[3] - 2),
        )
        variants.append(CropVariant("dob_loose", _clamp(loose, width, height), "DOB_LOOSE_TOP"))

    elif name in {"total_charge", "total_charges"}:
        cleared = (
            max(primary[0], cell_box[0] + int(0.28 * cell_w)),
            max(primary[1], cell_box[1] + 2),
            min(primary[2], cell_box[2] - 2),
            min(primary[3], cell_box[3] - 2),
        )
        variants.append(CropVariant("charge_npi_cleared", _clamp(cleared, width, height), "CHARGE_NPI_CLEARED"))
        taller = (
            max(primary[0], cell_box[0] + int(0.20 * cell_w)),
            max(primary[1], cell_box[1] + 1),
            min(primary[2], cell_box[2] - 1),
            min(primary[3], cell_box[3] - 1),
        )
        variants.append(CropVariant("charge_taller", _clamp(taller, width, height), "CHARGE_TALLER"))

    elif name in {"patient_name", "insured_name"}:
        value_band = (
            max(primary[0], cell_box[0] + 2),
            max(primary[1], cell_box[1] + int(0.35 * cell_h)),
            min(primary[2], cell_box[2] - 2),
            min(primary[3], cell_box[3] - 1),
        )
        variants.append(CropVariant("name_value_band", _clamp(value_band, width, height), "NAME_VALUE_BAND"))

    elif name in {"insured_id_number", "member_id"}:
        value_band = (
            max(primary[0], cell_box[0] + 2),
            max(primary[1], cell_box[1] + int(0.40 * cell_h)),
            min(primary[2], cell_box[2] - 2),
            min(primary[3], cell_box[3] - 1),
        )
        variants.append(CropVariant("id_value_band", _clamp(value_band, width, height), "ID_VALUE_BAND"))

    seen: set[tuple[int, int, int, int]] = set()
    unique: list[CropVariant] = []
    for variant in variants:
        if variant.bbox in seen:
            continue
        seen.add(variant.bbox)
        unique.append(variant)
    return unique


def charge_column_windows(primary_x0: int, primary_x1: int) -> list[tuple[str, int, int]]:
    """Alternate service-line charge x-windows (pointer-bleed avoidance)."""
    windows = [
        ("charges_primary", primary_x0, primary_x1),
        ("charges_mid", max(primary_x0, 1000), min(max(primary_x1, 1145), 1210)),
        ("charges_right", 1050, 1165),
    ]
    seen: set[tuple[int, int]] = set()
    out: list[tuple[str, int, int]] = []
    for variant_id, x0, x1 in windows:
        key = (x0, x1)
        if key in seen or x1 - x0 < 8:
            continue
        seen.add(key)
        out.append((variant_id, x0, x1))
    return out


class FieldCascade:
    """Execute the crop × engine cascade for one field."""

    def __init__(
        self,
        *,
        route_path: Path | None = None,
        strategy_id: str = "field-cascade-v3",
    ) -> None:
        self._route_path = route_path
        self.strategy_id = strategy_id

    def recognize(
        self,
        *,
        field_name: str,
        primary_bbox: tuple[int, int, int, int],
        cell: Mapping[str, int],
        image_size: tuple[int, int],
        recognize_fn: RecognizeFn,
        field_type: str = "",
    ) -> CascadeResult:
        engines = load_route_engines(field_name, self._route_path)
        variants = crop_variants(field_name, primary_bbox, cell, image_size)
        trace: list[CascadeStepResult] = []
        best: CascadeStepResult | None = None

        for variant in variants:
            candidates, attempts, reason = recognize_fn(
                field_name,
                variant.bbox,
                field_type,
                engines,
            )
            selected = next(
                (c.get("value") or "" for c in candidates if (c.get("value") or "").strip()),
                "",
            )
            raw = (candidates[0].get("raw_value") if candidates else "") or ""
            if not selected and raw:
                span = select_field_span(raw, span_datatype_for_field(field_name, field_type), field_name)
                selected = span.selected_text
            ok, accept_reason = semantic_accept(field_name, selected)
            step = CascadeStepResult(
                variant_id=variant.variant_id,
                bbox=variant.bbox,
                engines=engines,
                selected_value=selected,
                raw_value=raw,
                accepted=ok,
                accept_reason=accept_reason,
                candidates=tuple(candidates),
                attempts=tuple(attempts),
                router_reason=reason,
            )
            trace.append(step)
            if best is None or (selected and not (best.selected_value or "").strip()):
                best = step
            if ok:
                return CascadeResult(
                    field_name=field_name,
                    bbox=variant.bbox,
                    candidates=list(candidates),
                    attempts=list(attempts),
                    router_reason=reason,
                    status="OBSERVED",
                    cascade_trace=trace,
                    accepted=True,
                    accept_reason=accept_reason,
                    strategy_id=self.strategy_id,
                )

        if best is not None and best.candidates:
            return CascadeResult(
                field_name=field_name,
                bbox=best.bbox,
                candidates=list(best.candidates),
                attempts=list(best.attempts),
                router_reason=best.router_reason,
                status="OBSERVED" if best.selected_value else "NO_OBSERVATION",
                cascade_trace=trace,
                accepted=False,
                accept_reason=best.accept_reason,
                strategy_id=self.strategy_id,
            )
        return CascadeResult(
            field_name=field_name,
            bbox=primary_bbox,
            candidates=[],
            attempts=[],
            router_reason="EXHAUSTED",
            status="NO_OBSERVATION",
            cascade_trace=trace,
            accepted=False,
            accept_reason="EXHAUSTED",
            strategy_id=self.strategy_id,
        )
