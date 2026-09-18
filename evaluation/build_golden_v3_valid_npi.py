"""Build Golden Pack V3: Luhn-valid NPIs redrawn on images + updated truth.

Engineering-only STP measurement pack. Does not loosen production NPI policy.
Parent V2 remains unchanged. Dataset lives under evaluation_data/ (gitignored).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from packages.validation_rules.npi import is_valid_npi

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "evaluation_data/phase8_6_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V2"
V3 = ROOT / "evaluation_data/phase8_7_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V3"
OUTPUT = ROOT / "evaluation_results/phase8_7"
NPI_GENERATOR_VERSION = "synthetic-npi-80840-luhn-v1"
NPI_SEED = "phase8.7-valid-npi-seed-20260823"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _font(size: int, *, bold: bool = True) -> ImageFont.ImageFont:
    candidates = [
        Path("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/consola.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    if not bold:
        candidates = [
            Path("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
            *candidates,
        ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def generate_valid_npi(document_id: str) -> str:
    seed = hashlib.sha256(f"{NPI_SEED}:{document_id}".encode()).digest()
    first_nine = "1" + str(int.from_bytes(seed[:8], "big") % 100_000_000).zfill(8)
    for check_digit in range(10):
        candidate = first_nine + str(check_digit)
        if is_valid_npi(candidate):
            return candidate
    raise AssertionError(f"unable to generate valid NPI for {document_id}")


def _render_replacement_npi(
    image: Image.Image,
    value: str,
    bbox: list[int | float],
    variant: str,
    document_id: str,
) -> list[int]:
    x0, y0, x1, y1 = (round(item) for item in bbox)
    # Wider whiteout so adjacent form digits are less likely to glue onto the NPI.
    patch_box = (x0 - 8, y0 - 6, x1 + 10, y1 + 8)
    patch_width = patch_box[2] - patch_box[0]
    patch_height = patch_box[3] - patch_box[1]
    patch = Image.new("RGB", (patch_width, patch_height), "white")
    draw = ImageDraw.Draw(patch)
    # Keep engineering variants challenging, but stay OCR-readable for STP measurement.
    ink = 45 if variant == "low_contrast" else 0
    font_size = max(11, min(18, patch_height - 6))
    font = _font(font_size)
    left = top = right = bottom = 0
    while font_size >= 9:
        left, top, right, bottom = draw.textbbox((0, 0), value, font=font)
        text_width = right - left
        text_height = bottom - top
        if text_width <= patch_width - 8 and text_height <= patch_height - 4:
            break
        font_size -= 1
        font = _font(font_size)
    text_width = right - left
    text_height = bottom - top
    position = (
        max(2, (patch_width - text_width) // 2),
        max(1, (patch_height - text_height) // 2 - top),
    )
    draw.text(position, value, font=font, fill=(ink, ink, ink))
    # Do not re-apply blur/skew/noise onto the replacement digits. Parent images
    # already encode form-level variants; degrading the synthetic NPI patch
    # double-penalizes OCR and confounds STP measurement of Luhn-valid values.
    image.paste(patch, patch_box[:2])
    return [x0, y0, x1, y1]


def build(*, source: Path = V2, target: Path = V3, output: Path = OUTPUT, force: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if target.exists():
        manifest = json.loads((target / "manifest.json").read_text("utf-8"))
        if manifest.get("dataset_id") == "CDP_GOLDEN_ENGINEERING_PACK_V3" and not force:
            return manifest
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)

    manifest = json.loads((target / "manifest.json").read_text("utf-8"))
    documents = {row["document_id"]: row for row in manifest["documents"]}
    with (target / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))

    generated = []
    invalid_adversarial = []
    for row in truth:
        if row["field_name"] != "provider_npi":
            continue
        document_id = row["document_id"]
        old_value = row["expected_value"]
        if not is_valid_npi(old_value):
            invalid_adversarial.append(
                {
                    "document_id": document_id,
                    "value": old_value,
                    "intended_partition": "NPI_INVALID_ADVERSARIAL_CORPUS",
                }
            )
        new_value = generate_valid_npi(document_id)
        document = documents[document_id]
        image_path = target / document["file"]
        with Image.open(image_path) as source_image:
            image = source_image.convert("RGB")
        new_bbox = _render_replacement_npi(
            image,
            new_value,
            json.loads(row["bbox_json"]),
            document.get("variant", "clean"),
            document_id,
        )
        image.save(image_path)
        document["sha256"] = _sha(image_path)
        row["expected_value"] = new_value
        row["bbox_json"] = json.dumps(new_bbox)
        generated.append(
            {
                "document_id": document_id,
                "value": new_value,
                "generator_version": NPI_GENERATOR_VERSION,
                "validity_result": is_valid_npi(new_value),
            }
        )

    with (target / "field_truth.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=truth[0].keys())
        writer.writeheader()
        writer.writerows(truth)

    manifest.update(
        {
            "dataset_id": "CDP_GOLDEN_ENGINEERING_PACK_V3",
            "purpose": "PHI-free engineering STP measurement with business-valid blocking values.",
            "production_promotion_authority": False,
            "parent_dataset": "CDP_GOLDEN_ENGINEERING_PACK_V2",
            "parent_manifest_sha256": _sha(source / "manifest.json"),
            "npi_generator": {
                "version": NPI_GENERATOR_VERSION,
                "seed": NPI_SEED,
                "algorithm": "80840-prefix Luhn mod-10",
                "generated": len(generated),
                "valid": sum(row["validity_result"] for row in generated),
            },
            "partitions": {
                "NPI_VALID_STP_CORPUS": len(generated),
                "NPI_INVALID_ADVERSARIAL_CORPUS": len(invalid_adversarial),
            },
        }
    )
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    (target / "phase8_7_provenance.json").write_text(
        json.dumps(
            {
                "dataset_id": manifest["dataset_id"],
                "created_at": datetime.now(UTC).isoformat(),
                "builder": "evaluation/build_golden_v3_valid_npi.py",
                "v2_unchanged": True,
            },
            indent=2,
        )
        + "\n",
        "utf-8",
    )
    (output / "npi_valid_generation.json").write_text(
        json.dumps(generated, indent=2) + "\n", "utf-8"
    )
    (output / "npi_invalid_adversarial_cases.json").write_text(
        json.dumps(invalid_adversarial, indent=2) + "\n", "utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--source", type=Path, default=V2)
    parser.add_argument("--target", type=Path, default=V3)
    args = parser.parse_args()
    result = build(source=args.source, target=args.target, force=args.force)
    print(
        json.dumps(
            {
                "dataset_id": result["dataset_id"],
                "npi_generator": result.get("npi_generator"),
                "partitions": result.get("partitions"),
            },
            indent=2,
        )
    )
