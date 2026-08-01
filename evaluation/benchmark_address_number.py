"""Truth-blind digit recognition for the leading house-number address component."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps


def recognize(source: Image.Image, *, right_fraction: float = 0.24) -> dict:
    gray = source.convert("L")
    number = gray.crop((0, 1, max(1, int(gray.width * right_fraction)), gray.height - 2))
    base = ImageOps.expand(number, border=20, fill=255).resize(
        (number.width * 5, number.height * 5)
    )
    variants = {
        "gray": base,
        "contrast": ImageEnhance.Contrast(base).enhance(2.2),
        "threshold": base.point(lambda value: 255 if value > 175 else 0),
    }
    attempts = []
    with tempfile.TemporaryDirectory(prefix="idp-house-number-") as temporary:
        for variant, image in variants.items():
            path = Path(temporary) / f"{variant}.png"
            image.save(path)
            for psm in (6, 7, 8, 10, 13):
                completed = subprocess.run(
                    [
                        "tesseract", str(path), "stdout", "--psm", str(psm),
                        "-c", "tessedit_char_whitelist=0123456789",
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                value = "".join(character for character in completed.stdout if character.isdigit())
                attempts.append({"variant": variant, "psm": psm, "value": value})
    counts = Counter(row["value"] for row in attempts if 1 <= len(row["value"]) <= 8)
    winner, support = counts.most_common(1)[0] if counts else (None, 0)
    runner_up = counts.most_common(2)[1][1] if len(counts) > 1 else 0
    return {
        "value": winner if support >= 3 and support - runner_up >= 2 else None,
        "accepted": support >= 3 and support - runner_up >= 2,
        "support": support,
        "runner_up_support": runner_up,
        "attempts": attempts,
        "evaluation_truth_loaded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--right-fraction", type=float, default=0.24)
    args = parser.parse_args()
    with Image.open(args.crop) as source:
        result = recognize(source, right_fraction=args.right_fraction)
    result["crop"] = str(args.crop)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
