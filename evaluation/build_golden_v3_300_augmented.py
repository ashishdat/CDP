"""Build a 300-doc photometric expansion of Golden Pack V3.

The external Hackathon 1000-claims zip is not available in this environment.
This pack expands the 100 V3 engineering docs into 300 by cloning each image
with two OCR-stress photometric variants while keeping field truth and bboxes
unchanged (no geometric warp). Use for 300-sample Exact/HITL/STP measurement.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "evaluation_data/phase8_7_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V3"
OUT = ROOT / "evaluation_data/phase8_7_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V3_300"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _variant_image(image: Image.Image, kind: str, seed: str) -> Image.Image:
    rng = random.Random(seed)
    rgb = image.convert("RGB")
    if kind == "bright":
        rgb = ImageEnhance.Brightness(rgb).enhance(1.12)
        rgb = ImageEnhance.Contrast(rgb).enhance(0.92)
    elif kind == "soft":
        rgb = rgb.filter(ImageFilter.GaussianBlur(radius=0.45))
        rgb = ImageEnhance.Sharpness(rgb).enhance(0.85)
        noise = rgb.copy()
        pixels = noise.load()
        for _ in range(120):
            x = rng.randrange(noise.width)
            y = rng.randrange(noise.height)
            level = rng.choice((210, 225, 235))
            pixels[x, y] = (level, level, level)
        rgb = Image.blend(rgb, noise, 0.08)
    else:
        raise ValueError(kind)
    return rgb


def build(*, source: Path = V3, target: Path = OUT, force: bool = False) -> dict:
    if target.exists():
        manifest = json.loads((target / "manifest.json").read_text("utf-8"))
        if (
            manifest.get("dataset_id") == "CDP_GOLDEN_ENGINEERING_PACK_V3_300"
            and not force
        ):
            return manifest
        shutil.rmtree(target)
    target.mkdir(parents=True)

    source_manifest = json.loads((source / "manifest.json").read_text("utf-8"))
    source_truth = list(csv.DictReader((source / "field_truth.csv").open(encoding="utf-8")))
    documents = []
    truth_rows = []

    for doc in source_manifest["documents"]:
        variants = ("base", "bright", "soft")
        for variant in variants:
            if variant == "base":
                document_id = doc["document_id"]
                rel = doc["file"]
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / rel, dest)
                variant_name = doc.get("variant", "clean")
            else:
                document_id = f"{doc['document_id']}_{variant.upper()}"
                stem = Path(doc["file"])
                rel = str(stem.with_name(f"{stem.stem}_{variant}{stem.suffix}"))
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(source / doc["file"]) as image:
                    _variant_image(image, variant, f"{document_id}:{variant}").save(dest)
                variant_name = f"{doc.get('variant', 'clean')}+{variant}"
            documents.append(
                {
                    **doc,
                    "document_id": document_id,
                    "file": rel,
                    "sha256": _sha(dest),
                    "variant": variant_name,
                    "parent_document_id": doc["document_id"],
                    "photometric_variant": variant,
                }
            )
            for row in source_truth:
                if row["document_id"] != doc["document_id"]:
                    continue
                truth_rows.append({**row, "document_id": document_id})

    with (target / "field_truth.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=truth_rows[0].keys())
        writer.writeheader()
        writer.writerows(truth_rows)

    # Preserve service-line truth if present, remapped to expanded ids.
    service_src = source / "ub04_service_line_truth.csv"
    if service_src.exists():
        service_rows = list(csv.DictReader(service_src.open(encoding="utf-8")))
        expanded = []
        for doc in source_manifest["documents"]:
            for variant in ("base", "bright", "soft"):
                document_id = (
                    doc["document_id"]
                    if variant == "base"
                    else f"{doc['document_id']}_{variant.upper()}"
                )
                for row in service_rows:
                    if row["document_id"] != doc["document_id"]:
                        continue
                    expanded.append({**row, "document_id": document_id})
        if expanded:
            with (target / "ub04_service_line_truth.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=expanded[0].keys())
                writer.writeheader()
                writer.writerows(expanded)

    for name in ("README.md", "README_PHASE8_6.md", "phase8_6_provenance.json"):
        src = source / name
        if src.exists():
            shutil.copy2(src, target / name)

    cms = sum(1 for doc in documents if str(doc["document_id"]).startswith("CMS"))
    ub = sum(1 for doc in documents if str(doc["document_id"]).startswith("UB"))
    manifest = {
        **source_manifest,
        "dataset_id": "CDP_GOLDEN_ENGINEERING_PACK_V3_300",
        "parent_dataset": source_manifest.get("dataset_id"),
        "purpose": (
            "300-sample photometric expansion of Golden V3 for Exact/HITL/STP "
            "measurement. Not a substitute for the external 1000-claim corpus."
        ),
        "document_count": len(documents),
        "documents": documents,
        "expansion": {
            "method": "photometric_clone_v1",
            "variants_per_source": 3,
            "cms_docs": cms,
            "ub_docs": ub,
            "geometric_warp": False,
            "truth_bboxes_unchanged": True,
        },
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--source", type=Path, default=V3)
    parser.add_argument("--target", type=Path, default=OUT)
    args = parser.parse_args()
    result = build(source=args.source, target=args.target, force=args.force)
    print(
        json.dumps(
            {
                "dataset_id": result["dataset_id"],
                "document_count": result["document_count"],
                "expansion": result.get("expansion"),
            },
            indent=2,
        )
    )
