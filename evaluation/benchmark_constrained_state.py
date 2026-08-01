"""Run truth-blind, constrained OCR profiles over isolated US-state crops."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

VALID_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def variants(source: Image.Image) -> dict[str, Image.Image]:
    gray = source.convert("L")
    # Remove form rules without erasing ascenders that touch them.
    inner = gray.crop((max(0, gray.width // 14), 2, gray.width - 2, gray.height - 3))
    inner = ImageOps.expand(inner, border=18, fill=255).resize(
        (inner.width * 4, inner.height * 4)
    )
    contrast = ImageEnhance.Contrast(inner).enhance(2.0)
    return {
        "gray_4x": inner,
        "contrast_4x": contrast,
        "threshold_4x": contrast.point(lambda value: 255 if value > 175 else 0),
        "median_threshold_4x": contrast.filter(ImageFilter.MedianFilter(3)).point(
            lambda value: 255 if value > 175 else 0
        ),
    }


def recognize(source: Image.Image) -> dict:
    attempts = []
    with tempfile.TemporaryDirectory(prefix="idp-state-") as temporary:
        for variant_name, image in variants(source).items():
            path = Path(temporary) / f"{variant_name}.png"
            image.save(path)
            for psm in (6, 7, 8, 10, 13):
                completed = subprocess.run(
                    [
                        "tesseract", str(path), "stdout", "--psm", str(psm),
                        "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                value = "".join(completed.stdout.upper().split())
                attempts.append({
                    "variant": variant_name, "psm": psm, "value": value,
                    "valid_state": value in VALID_STATES,
                })
    valid = [row["value"] for row in attempts if row["valid_state"]]
    counts = Counter(valid)
    winner, support = counts.most_common(1)[0] if counts else (None, 0)
    runner_up = counts.most_common(2)[1][1] if len(counts) > 1 else 0
    accepted = winner is not None and support >= 3 and support - runner_up >= 2
    return {
        "value": winner if accepted else None,
        "accepted": accepted,
        "support": support,
        "runner_up_support": runner_up,
        "attempts": attempts,
        "evaluation_truth_loaded": False,
    }


def recognize_duplicate(patient: Image.Image, insured: Image.Image) -> dict:
    """Require matching valid state text from two distinct form regions."""
    region_results = []
    with tempfile.TemporaryDirectory(prefix="idp-duplicate-state-") as temporary:
        for region_name, source in (("patient", patient), ("insured", insured)):
            path = Path(temporary) / f"{region_name}.png"
            source.convert("L").save(path)
            values = []
            for psm in (6, 7, 10):
                completed = subprocess.run(
                    [
                        "tesseract", str(path), "stdout", "--psm", str(psm),
                        "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                values.append("".join(completed.stdout.upper().split()))
            consensus = values[0] if len(set(values)) == 1 and values[0] in VALID_STATES else None
            region_results.append({"region": region_name, "values": values, "consensus": consensus})
    winners = {row["consensus"] for row in region_results if row["consensus"]}
    accepted = len(winners) == 1 and all(row["consensus"] for row in region_results)
    return {
        "value": winners.pop() if accepted else None,
        "accepted": accepted,
        "regions": region_results,
        "evidence_role": "DUPLICATE_REGIONAL_EVIDENCE",
        "evaluation_truth_loaded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duplicate-crop", type=Path)
    args = parser.parse_args()
    with Image.open(args.crop) as source:
        if args.duplicate_crop:
            with Image.open(args.duplicate_crop) as duplicate:
                result = recognize_duplicate(source, duplicate)
        else:
            result = recognize(source)
    result["crop"] = str(args.crop)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
