"""Decode page QR evidence without using evaluation labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    image = cv2.imread(str(args.image))
    value, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    print(json.dumps({"decoded": value or None, "detected": points is not None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
