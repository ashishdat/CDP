"""Template-defined semantic crops for fixed-form service lines."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from workers.table_extraction.active_row_detection import classify_row
from workers.table_extraction.template_registration import load_spec


@dataclass(frozen=True)
class SemanticCell:
    form_version: str
    form_locator: str
    service_line_number: int
    semantic_field_name: str
    data_type: str
    validation_policy: str
    template_bbox: tuple[int, int, int, int]
    registered_bbox: tuple[int, int, int, int]
    crop: Image.Image


def extract_semantic_rows(page: Image.Image, family: str) -> list[dict]:
    spec = load_spec(family)
    rows = spec["rows"]
    left, top, right, bottom = spec["internal_padding"]
    row_height = (rows["last_y"] - rows["first_y"]) / rows["count"]
    extracted = []
    evidence_fields = (
        {"procedure_code", "date_from", "charges", "service_units"}
        if family == "CMS1500"
        else {"revenue_code", "description", "hcpcs_rate_hipps_code", "service_date", "total_charges"}
    )
    for row_index in range(rows["count"]):
        y0 = round(rows["first_y"] + row_index * row_height)
        y1 = round(rows["first_y"] + (row_index + 1) * row_height)
        cells = []
        crops = {}
        for field in spec["fields"]:
            field_left, field_top, field_right, field_bottom = field.get(
                "internal_padding", (left, top, right, bottom)
            )
            template_bbox = (field["x0"], y0, field["x1"], y1)
            registered_bbox = (
                field["x0"] + field_left,
                y0 + field_top,
                field["x1"] - field_right,
                y1 - field_bottom,
            )
            crop = page.crop(registered_bbox)
            crops[field["semantic_field_name"]] = crop
            cells.append(
                SemanticCell(
                    form_version=spec["form_version"],
                    form_locator=field["form_locator"],
                    service_line_number=row_index + 1,
                    semantic_field_name=field["semantic_field_name"],
                    data_type=field["data_type"],
                    validation_policy=field["validation_policy"],
                    template_bbox=template_bbox,
                    registered_bbox=registered_bbox,
                    crop=crop,
                )
            )
        extracted.append(
            {
                "service_line_number": row_index + 1,
                **classify_row(crops, evidence_fields),
                "cells": cells,
                "row_bbox": (
                    spec["fields"][0]["x0"],
                    y0,
                    spec["fields"][-1]["x1"],
                    y1,
                ),
            }
        )
    return extracted
