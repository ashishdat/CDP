"""Render a PHI-local contact sheet for manual routing diagnostics."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw/Group D"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation_results/unstructured_inventory/contact_sheet.png"),
    )
    parser.add_argument("--source-name")
    parser.add_argument("--page-number", type=int)
    parser.add_argument("--page-output", type=Path)
    args = parser.parse_args()
    if args.source_name and args.page_number and args.page_output:
        with Image.open(args.dataset / args.source_name) as document:
            document.seek(args.page_number - 1)
            image = document.convert("RGB")
        args.page_output.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.page_output, "PNG")
        print(args.page_output)
        return 0
    tiles: list[tuple[str, Image.Image]] = []
    for source in sorted(args.dataset.glob("M*")):
        with Image.open(source) as document:
            for index in range(getattr(document, "n_frames", 1)):
                document.seek(index)
                tiles.append(
                    (
                        f"{source.name} p{index + 1}",
                        ImageOps.contain(document.convert("RGB"), (260, 340)),
                    )
                )
    width, tile_h, columns = 900, 380, 3
    sheet = Image.new(
        "RGB", (width, tile_h * ((len(tiles) + columns - 1) // columns)), "white"
    )
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(tiles):
        x = (index % columns) * (width // columns)
        y = (index // columns) * tile_h
        draw.text((x + 8, y + 5), label, fill="black")
        sheet.paste(image, (x + 8, y + 28))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, "PNG")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
