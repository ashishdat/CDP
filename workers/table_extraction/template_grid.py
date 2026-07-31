"""Versioned template-defined service-line cells for standard claim forms."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image

from workers.cascade.tesseract_adapter import TesseractTextExtractor

TEMPLATES = {
    "CMS1500": Path("config/templates/cms1500_v02_12.yaml"),
    "UB04": Path("config/templates/ub04_v2014.yaml"),
}


def _usable_token_text(text: str) -> bool:
    if "\t" in text or "\n" in text or "\r" in text:
        return False
    value = text.strip()
    if not value or len(value) > 120:
        return False
    # A TSV record accidentally captured as text contains many numeric fields
    # separated by whitespace; it is not visible document evidence.
    return not bool(re.match(r"^\d+(?:\s+\d+){5,}", value))


@dataclass(frozen=True)
class TemplateCell:
    row_index: int
    column_name: str
    field_type: str
    bbox: tuple[int, int, int, int]
    raw_text: str
    confidence: float


@dataclass(frozen=True)
class TemplateGrid:
    bbox: tuple[int, int, int, int]
    cells: list[TemplateCell]
    template_version: str
    transform: list[list[float]]


def extract_template_grid(page: Image.Image, family: str) -> TemplateGrid:
    spec = yaml.safe_load(TEMPLATES[family].read_text(encoding="utf-8"))
    shadow = yaml.safe_load(
        Path("config/table_shadow_v2.yaml").read_text(encoding="utf-8")
    )
    reference = spec["reference_dimensions"]
    scale_x = page.width / reference["width_px"]
    scale_y = page.height / reference["height_px"]
    service = spec["service_line_region"]
    override = shadow.get("grid_overrides", {}).get(family, {})

    def scale_box(x0: float, y0: float, x1: float, y1: float):
        return (
            round(x0 * scale_x), round(y0 * scale_y),
            round(x1 * scale_x), round(y1 * scale_y),
        )

    data_y0 = override.get("data_y0", service["table_y0"])
    data_y1 = override.get("data_y1", service["table_y1"])
    table_bbox = scale_box(
        service["table_x0"], data_y0,
        service["table_x1"], data_y1,
    )
    # One OCR pass preserves token geometry; cells receive only tokens whose
    # centres fall inside their template-defined boundary.
    tokens = [
        token for token in TesseractTextExtractor(psm=6).extract_region(
            page, *table_bbox
        )
        if _usable_token_text(token.text)
    ]
    cells = []
    row_height = (data_y1 - data_y0) / service["max_rows"]
    column_overrides = override.get("columns", {})
    for row_index in range(service["max_rows"]):
        y0 = data_y0 + row_index * row_height
        y1 = data_y0 + (row_index + 1) * row_height
        for column in service["columns"]:
            x0, x1 = column_overrides.get(
                column["field_name"], (column["x0"], column["x1"])
            )
            bbox = scale_box(x0, y0, x1, y1)
            matches = [
                token for token in tokens
                if bbox[0] <= (token.x0 + token.x1) / 2 < bbox[2]
                and bbox[1] <= (token.y0 + token.y1) / 2 < bbox[3]
            ]
            matches.sort(key=lambda token: (token.y0, token.x0))
            cells.append(TemplateCell(
                row_index=row_index,
                column_name=column["field_name"],
                field_type=column["field_type"],
                bbox=bbox,
                raw_text=" ".join(token.text for token in matches),
                confidence=(
                    sum(token.confidence for token in matches) / len(matches)
                    if matches else 0.0
                ),
            ))
    return TemplateGrid(
        bbox=table_bbox,
        cells=cells,
        template_version=str(spec["version"]),
        transform=[
            [scale_x, 0.0, 0.0],
            [0.0, scale_y, 0.0],
            [0.0, 0.0, 1.0],
        ],
    )
