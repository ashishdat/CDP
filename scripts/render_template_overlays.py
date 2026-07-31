"""Render every configured field region over its local reference image."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from PIL import ImageDraw

from packages.templates.registry import TemplateRegistry

COLORS = ("#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--templates", type=Path, default=Path("config/templates"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/template_overlays"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    registry = TemplateRegistry.load_from_directory(args.templates)
    contract = yaml.safe_load(
        Path("config/evaluation/field_contract.yaml").read_text(encoding="utf-8")
    )
    for template in [
        registry.get("cms1500", "02-12"),
        registry.get("ub04", "2014"),
    ]:
        reference = registry.load_reference_image(template)
        if reference is None:
            raise FileNotFoundError(f"Missing reference for {template.template_id}")
        canvas = reference.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        contract_fields = set(contract["forms"][template.form_type.value]["fields"])
        regions = [region for region in template.field_regions if region.field_name in contract_fields]
        for index, region in enumerate(regions):
            color = COLORS[index % len(COLORS)]
            draw.rectangle((region.x0, region.y0, region.x1, region.y1), outline=color, width=3)
            draw.rectangle(
                (region.x0, max(0, region.y0 - 18), region.x0 + len(region.field_name) * 8, region.y0),
                fill=color,
            )
            draw.text((region.x0 + 2, max(0, region.y0 - 17)), region.field_name, fill="white")
        target = args.output / f"{template.template_id}.png"
        canvas.save(target, "PNG", optimize=True)
        print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
