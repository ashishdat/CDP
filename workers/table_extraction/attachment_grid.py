"""Named, anchor-gated grids for supported attachment layout variants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image

from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.table_extraction.template_grid import (
    TemplateCell,
    TemplateGrid,
    _usable_token_text,
)

SPECS = {
    "laboratory_invoice": Path("config/layout_templates/laboratory_invoice.yaml"),
    "statement": Path("config/layout_templates/statement.yaml"),
}


@dataclass(frozen=True)
class AttachmentGridResult:
    grid: TemplateGrid | None
    variant: str
    failure_reason: str | None


def _contains_anchor(text: str, anchor: str) -> bool:
    compact_text = re.sub(r"[^A-Z0-9]", "", text.upper())
    compact_anchor = re.sub(r"[^A-Z0-9]", "", anchor.upper())
    return compact_anchor in compact_text


def extract_attachment_grid(
    page: Image.Image, family: str
) -> AttachmentGridResult:
    spec = yaml.safe_load(SPECS[family].read_text(encoding="utf-8"))
    grid_spec = spec["table_grid"]
    full_tokens = [
        token for token in TesseractTextExtractor(psm=11).extract(page)
        if _usable_token_text(token.text)
    ]
    full_text = " ".join(token.text for token in full_tokens)
    missing = [
        anchor for anchor in grid_spec["required_anchors"]
        if not _contains_anchor(full_text, anchor)
    ]
    if missing:
        return AttachmentGridResult(
            grid=None,
            variant=grid_spec["variant"],
            failure_reason="ANCHOR_VARIANT_MISMATCH",
        )
    region = grid_spec["data_region"]
    table_bbox = (
        round(region["x0"] * page.width), round(region["y0"] * page.height),
        round(region["x1"] * page.width), round(region["y1"] * page.height),
    )
    tokens = [
        token for token in full_tokens
        if table_bbox[0] <= (token.x0 + token.x1) / 2 < table_bbox[2]
        and table_bbox[1] <= (token.y0 + token.y1) / 2 < table_bbox[3]
    ]
    if grid_spec["row_mode"] == "OCR_LINE_CLUSTER":
        tolerance = grid_spec["row_tolerance_ratio"] * page.height
        centres: list[float] = []
        for token in sorted(tokens, key=lambda item: (item.y0 + item.y1) / 2):
            centre = (token.y0 + token.y1) / 2
            if not centres or abs(centre - centres[-1]) > tolerance:
                centres.append(centre)
            else:
                centres[-1] = (centres[-1] + centre) / 2
        row_edges = []
        for index, centre in enumerate(centres):
            top = (
                table_bbox[1] if index == 0
                else round((centres[index - 1] + centre) / 2)
            )
            bottom = (
                table_bbox[3] if index == len(centres) - 1
                else round((centre + centres[index + 1]) / 2)
            )
            row_text = " ".join(
                token.text for token in tokens if top <= (token.y0 + token.y1) / 2 < bottom
            )
            compact_row = re.sub(r"[^A-Z0-9]", "", row_text.upper())
            if "TAX" not in compact_row and "SERVIC" not in compact_row:
                row_edges.append((top, bottom))
    else:
        height = (table_bbox[3] - table_bbox[1]) / grid_spec["row_count"]
        row_edges = [
            (
                round(table_bbox[1] + row * height),
                round(table_bbox[1] + (row + 1) * height),
            )
            for row in range(grid_spec["row_count"])
        ]
    cells = []
    for row_index, (top, bottom) in enumerate(row_edges):
        for column in grid_spec["columns"]:
            bbox = (
                round(column["x0"] * page.width), top,
                round(column["x1"] * page.width), bottom,
            )
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
    return AttachmentGridResult(
        grid=TemplateGrid(
            bbox=table_bbox,
            cells=cells,
            template_version=str(spec["version"]),
            transform=[
                [page.width / spec["reference_dimensions"][0], 0.0, 0.0],
                [0.0, page.height / spec["reference_dimensions"][1], 0.0],
                [0.0, 0.0, 1.0],
            ],
        ),
        variant=grid_spec["variant"],
        failure_reason=None,
    )
