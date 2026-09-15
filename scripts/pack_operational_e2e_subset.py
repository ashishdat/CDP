#!/usr/bin/env python3
"""Build a 100-claim subset ZIP for operational E2E (Windows-friendly).

Run this on the machine that already has the full Hackathon archive:

  python scripts/pack_operational_e2e_subset.py ^
    --source "C:\\Users\\ashish.singh\\Downloads\\key docs\\Hackathon - 1000 Claims.zip"

This writes:
  data/Hackathon-100-ops-subset.zip
  data/dataset_ops_100.yaml

Then either:
  A) Host the subset ZIP (Drive/Dropbox/S3) and paste DATASET_URL=... in chat, or
  B) Split for chat (<=9 MiB parts) — only if the subset is still too large to host:

  python scripts/pack_operational_e2e_subset.py ... --split-mb 9
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datasets.registry import REGISTRY  # noqa: E402

DEFAULT_OPS = ROOT / "AnchorNormalizationDeltaReport.json"
OPS_META = REGISTRY["OPERATIONAL_E2E_100_V1"]


def _docs_from_ops(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    docs = [row["document"] for row in payload.get("paired_claims") or []]
    if len(docs) != OPS_META.documents:
        raise SystemExit(
            f"Expected {OPS_META.documents} paired_claims, found {len(docs)} in {path}"
        )
    return docs


def _split_file(path: Path, chunk_mb: float) -> list[Path]:
    chunk_size = max(1, int(chunk_mb * 1024 * 1024))
    data = path.read_bytes()
    parts: list[Path] = []
    total = math.ceil(len(data) / chunk_size)
    for index in range(total):
        part = path.with_name(f"{path.name}.part{index:03d}-of-{total:03d}")
        start = index * chunk_size
        part.write_bytes(data[start : start + chunk_size])
        parts.append(part)
        print(f"Wrote {part.name} ({part.stat().st_size} bytes)")
    manifest = path.with_suffix(path.suffix + ".parts.json")
    manifest.write_text(
        json.dumps(
            {
                "original_name": path.name,
                "original_size": len(data),
                "chunk_bytes": chunk_size,
                "parts": [p.name for p in parts],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {manifest}")
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Full Hackathon ZIP")
    parser.add_argument("--ops-report", type=Path, default=DEFAULT_OPS)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "Hackathon-100-ops-subset.zip",
    )
    parser.add_argument(
        "--dataset-yaml",
        type=Path,
        default=ROOT / "data" / "dataset_ops_100.yaml",
    )
    parser.add_argument(
        "--split-mb",
        type=float,
        default=0.0,
        help="If >0, also emit chat-sized part files (e.g. 9).",
    )
    args = parser.parse_args()

    if not args.source.exists():
        raise SystemExit(f"Source ZIP not found: {args.source}")

    docs = set(_docs_from_ops(args.ops_report))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    pages = 0
    missing: list[str] = []
    with ZipFile(args.source, "r") as src, ZipFile(args.output, "w") as dst:
        names = {info.filename: info for info in src.infolist() if not info.is_dir()}
        for document in sorted(docs):
            info = names.get(document)
            if info is None:
                missing.append(document)
                continue
            payload = src.read(info)
            with Image.open(BytesIO(payload)) as image:
                pages += image.n_frames
            dst.writestr(info.filename, payload)
            written += 1

    if missing:
        raise SystemExit(
            f"Missing {len(missing)} documents in source ZIP; first={missing[0]!r}"
        )
    if written != OPS_META.documents:
        raise SystemExit(f"Expected {OPS_META.documents} docs, wrote {written}")
    if pages != OPS_META.pages:
        raise SystemExit(
            f"Expected {OPS_META.pages} pages from paired_claims, counted {pages} "
            "image frames in the subset ZIP"
        )

    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.output} with {written} documents / {pages} pages ({size_mb:.1f} MiB)")
    print(f"SHA-256: {digest}")

    # Root is relative to the YAML location (data/).
    root_name = args.output.name if args.output.parent == args.dataset_yaml.parent else str(
        args.output
    )
    config = {
        "dataset_id": OPS_META.dataset_id,
        "root": root_name,
        "pages": OPS_META.pages,
        "documents": OPS_META.documents,
        "description": OPS_META.description,
        "hash": digest,
    }
    args.dataset_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(f"Wrote {args.dataset_yaml}")

    if args.split_mb > 0:
        parts = _split_file(args.output, args.split_mb)
        print(f"Split into {len(parts)} parts for <= {args.split_mb} MiB chat upload")
        print("Also keep/upload the dataset_ops_100.yaml (tiny) with the parts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
