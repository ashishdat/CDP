"""OCR every Group-D page for document-family and anchor discovery.

This produces inference evidence only. It never reads ground truth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.page_detection.text_extraction import PaddleOCRTextExtractor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw/Group D"))
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation_results/unstructured_inventory")
    )
    parser.add_argument("--source-name")
    parser.add_argument("--page-number", type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paddle = PaddleOCRTextExtractor()
    tesseract = TesseractTextExtractor(psm=6)
    index: dict[str, list[dict]] = {}
    for source in sorted(args.dataset.glob("M*")):
        if args.source_name and source.name != args.source_name:
            continue
        pages: list[dict] = []
        with Image.open(source) as document:
            for page_index in range(getattr(document, "n_frames", 1)):
                if args.page_number and page_index + 1 != args.page_number:
                    continue
                document.seek(page_index)
                image = document.convert("RGB")
                cache = args.output / f"{source.name}.page-{page_index + 1}.paddle.json"
                if cache.is_file():
                    lines = json.loads(cache.read_text(encoding="utf-8"))
                else:
                    extracted = paddle.extract(image)
                    if len(extracted) < 3:
                        extracted = tesseract.extract(image)
                    lines = [line.__dict__ for line in extracted]
                    cache.write_text(json.dumps(lines), encoding="utf-8")
                text = "\n".join(line["text"] for line in lines)
                pages.append({
                    "page_number": page_index + 1,
                    "width": image.width,
                    "height": image.height,
                    "text": text,
                    "line_count": len(lines),
                    "ocr_cache": str(cache).replace("\\", "/"),
                })
                print(source.name, page_index + 1, len(lines))
        index[source.name] = pages
    (args.output / "index.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
