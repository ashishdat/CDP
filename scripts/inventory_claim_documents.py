"""Inventory every numbered TIFF as a complete multipage claim document."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

EXPECTED = {
    "A": [1] * 12,
    "B": [2, 2, 3, 7, 7],
    "C": [1] * 6,
    "D": [2, 2, 3, 9, 4, 4, 4],
}


def _dhash(image: Image.Image) -> str:
    gray = image.convert("L").resize((9, 8))
    pixels = list(gray.getdata())
    bits = [
        pixels[row * 9 + column] > pixels[row * 9 + column + 1]
        for row in range(8) for column in range(8)
    ]
    return f"{sum(int(bit) << index for index, bit in enumerate(bits)):016x}"


def _quality(image: Image.Image) -> dict[str, float]:
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return {
        "mean_luminance": round(ImageStat.Stat(gray).mean[0], 3),
        "contrast_stddev": round(ImageStat.Stat(gray).stddev[0], 3),
        "edge_mean": round(ImageStat.Stat(edges).mean[0], 3),
    }


def _candidates(group: str) -> list[str]:
    return {
        "A": ["CMS1500"],
        "B": ["CMS1500", "CMS_ATTACHMENT", "UNKNOWN"],
        "C": ["UB_INSTITUTIONAL"],
        "D": [
            "PSYCHOLOGICAL_RECEIPT", "LABORATORY_INVOICE",
            "STATEMENT", "CMS_ATTACHMENT", "UNKNOWN",
        ],
    }[group]


def build_inventory(dataset: Path) -> dict[str, object]:
    documents = []
    mismatches = []
    for group, expected_counts in EXPECTED.items():
        paths = sorted(
            path for path in (dataset / f"Group {group}").iterdir()
            if path.suffix.lower() not in {".txt", ".json", ".csv"}
        )
        if len(paths) != len(expected_counts):
            mismatches.append(
                f"Group {group}: expected {len(expected_counts)} documents, found {len(paths)}"
            )
        for index, path in enumerate(paths, start=1):
            pages = []
            with Image.open(path) as image:
                page_count = getattr(image, "n_frames", 1)
                for page_index in range(page_count):
                    image.seek(page_index)
                    page = image.copy()
                    compression = image.info.get("compression", "unknown")
                    pages.append({
                        "page_number": page_index + 1,
                        "width": page.width,
                        "height": page.height,
                        "compression": str(compression),
                        "perceptual_hash": _dhash(page),
                        "quality": _quality(page),
                        "page_family_candidates": _candidates(group),
                    })
            expected = expected_counts[index - 1] if index <= len(expected_counts) else None
            if expected is not None and page_count != expected:
                mismatches.append(
                    f"{group}-{index:02d}: expected {expected} pages, found {page_count}"
                )
            documents.append({
                "document_id_hash": hashlib.sha256(
                    f"Group {group}/{path.name}".encode()
                ).hexdigest(),
                "group": group,
                "document_name": path.name,
                "page_count": page_count,
                "pages": pages,
            })
    return {
        "schema_version": "1",
        "documents": documents,
        "summary": {
            "document_count": len(documents),
            "page_count": sum(item["page_count"] for item in documents),
            "expected_page_counts": EXPECTED,
            "mismatches": mismatches,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation_results/document_inventory/inventory.json"),
    )
    args = parser.parse_args()
    inventory = build_inventory(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(json.dumps(inventory["summary"], indent=2))
    return 1 if inventory["summary"]["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
