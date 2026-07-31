"""Run OCR on one image and emit machine-readable line geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from workers.page_detection.text_extraction import PaddleOCRTextExtractor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    extractor = PaddleOCRTextExtractor()
    with Image.open(args.image) as image:
        lines = extractor.extract(image.convert("RGB"))
    print(json.dumps([line.__dict__ for line in lines], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
