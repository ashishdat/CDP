"""Anchor-relative field crops for recurring unstructured document families."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class AnchorCrop:
    field_name: str
    anchor: str
    crop: Image.Image
    box: tuple[int, int, int, int]
    anchor_confidence: float


def extract_anchor_crops(
    page: Image.Image,
    lines: list[TextLine],
    field_specs: dict,
) -> dict[str, AnchorCrop]:
    results: dict[str, AnchorCrop] = {}
    for field_name, spec in field_specs.items():
        match = _best_anchor(lines, spec.get("anchors", []))
        if match is None:
            continue
        anchor_text, anchor_line, anchor_score = match
        direction = spec.get("direction", "right_or_below")
        offset_x = int(spec.get("offset_x", 0))
        offset_y = int(spec.get("offset_y", 0))
        anchor_lower = next(
            (anchor.lower() for anchor in spec.get("anchors", [])
             if anchor.lower() in anchor_line.text.lower()),
            "",
        )
        trailing = (
            anchor_line.text.lower().split(anchor_lower, 1)[1].strip(" :-")
            if anchor_lower else ""
        )
        if (
            trailing
            and not any(label in trailing for label in ("last name", "first name", "middle"))
            and spec.get("field_type") == "person_name"
        ):
            anchor_fraction = min(
                len(anchor_lower) / max(len(anchor_line.text), 1), 0.8
            )
            x0 = int(
                anchor_line.x0
                + (anchor_line.x1 - anchor_line.x0) * anchor_fraction
                - 4
            )
            y0 = int(anchor_line.y0 - 8)
            width = int(anchor_line.x1 - x0 + 8)
            height = int(anchor_line.y1 - anchor_line.y0 + 16)
            box = (
                max(0, x0), max(0, y0),
                min(page.width, x0 + width), min(page.height, y0 + height),
            )
            results[field_name] = AnchorCrop(
                field_name, anchor_text, page.crop(box), box, anchor_score
            )
            continue
        if direction == "below":
            x0 = int(anchor_line.x0 + offset_x)
            y0 = int(anchor_line.y1 + offset_y)
        else:
            x0 = int(anchor_line.x1 + 8 + offset_x)
            y0 = int(anchor_line.y0 + offset_y)
            # A label-only anchor commonly has its value on the next line.
            if x0 + 40 >= page.width:
                x0, y0 = int(anchor_line.x0), int(anchor_line.y1 + offset_y)
        width = int(spec.get("width_px", 700))
        height = int(spec.get("height_px", 100))
        box = (
            max(0, x0),
            max(0, y0),
            min(page.width, x0 + width),
            min(page.height, y0 + height),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        results[field_name] = AnchorCrop(
            field_name, anchor_text, page.crop(box), box, anchor_score
        )
    return results


def _best_anchor(
    lines: list[TextLine], anchors: list[str]
) -> tuple[str, TextLine, float] | None:
    candidates = []
    for line in lines:
        text = line.text.lower()
        for anchor in anchors:
            anchor_lower = anchor.lower()
            if anchor_lower in text:
                candidates.append((anchor, line, line.confidence))
    return max(candidates, key=lambda item: item[2], default=None)
