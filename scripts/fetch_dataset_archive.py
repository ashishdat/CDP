#!/usr/bin/env python3
"""Download or reassemble the Hackathon archive into data/.

Preferred (avoids the ~10 MB chat upload limit):

  # Full 1000-claim archive
  python scripts/fetch_dataset_archive.py --url "https://.../Hackathon - 1000 Claims.zip"

  # 100-claim operational subset (also writes data/dataset_ops_100.yaml)
  python scripts/fetch_dataset_archive.py --url "https://.../Hackathon-100-ops-subset.zip" --as-ops-subset

Chat chunk reassembly (after uploading *.part* files into data/incoming/):

  python scripts/fetch_dataset_archive.py --reassemble-dir data/incoming --as-ops-subset
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datasets.registry import REGISTRY

DEFAULT_FULL_OUT = ROOT / "data" / "Hackathon - 1000 Claims.zip"
DEFAULT_OPS_OUT = ROOT / "data" / "Hackathon-100-ops-subset.zip"
OPS_YAML = ROOT / "data" / "dataset_ops_100.yaml"
OPS_META = REGISTRY["OPERATIONAL_E2E_100_V1"]
EXPECTED_FULL_SHA256 = REGISTRY["DEVELOPMENT_DATASET_V1"].hash


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=600) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(dest)
    print(f"Wrote {dest} ({dest.stat().st_size} bytes)")


def _reassemble(directory: Path, dest: Path) -> None:
    directory = directory.resolve()
    manifests = sorted(directory.glob("*.parts.json"))
    if not manifests:
        parts = sorted(directory.glob("*.part*-of-*"))
        if not parts:
            raise SystemExit(f"No part files or manifest found in {directory}")
        print("No manifest; concatenating part files in sorted order")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as out:
            for part in parts:
                out.write(part.read_bytes())
                print(f"Appended {part.name}")
        print(f"Wrote {dest} ({dest.stat().st_size} bytes)")
        return

    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    parts = [directory / name for name in manifest["parts"]]
    missing = [str(path) for path in parts if not path.exists()]
    if missing:
        raise SystemExit(f"Missing parts: {missing}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        for part in parts:
            out.write(part.read_bytes())
            print(f"Appended {part.name}")
    size = dest.stat().st_size
    expected = manifest.get("original_size")
    if expected is not None and size != expected:
        raise SystemExit(f"Reassembled size {size} != expected {expected}")
    print(f"Wrote {dest} ({size} bytes)")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_ops_yaml(archive: Path) -> None:
    pages = 0
    with ZipFile(archive, "r") as zf:
        entries = [info for info in zf.infolist() if not info.is_dir()]
        if len(entries) != OPS_META.documents:
            raise SystemExit(
                f"Ops subset must contain {OPS_META.documents} documents; found {len(entries)}"
            )
        for info in entries:
            with Image.open(BytesIO(zf.read(info))) as image:
                pages += image.n_frames
    if pages != OPS_META.pages:
        raise SystemExit(
            f"Ops subset must contain {OPS_META.pages} pages; found {pages}"
        )
    digest = _sha256(archive)
    config = {
        "dataset_id": OPS_META.dataset_id,
        "root": archive.name,
        "pages": OPS_META.pages,
        "documents": OPS_META.documents,
        "description": OPS_META.description,
        "hash": digest,
    }
    OPS_YAML.parent.mkdir(parents=True, exist_ok=True)
    OPS_YAML.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(f"Wrote {OPS_YAML}")
    print(f"Ops subset SHA-256: {digest}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Direct download URL for the ZIP")
    parser.add_argument(
        "--reassemble-dir",
        type=Path,
        help="Directory containing .part* files and optional .parts.json",
    )
    parser.add_argument(
        "--as-ops-subset",
        action="store_true",
        help="Treat archive as the 100-claim ops subset and write dataset_ops_100.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination ZIP path (defaults depend on --as-ops-subset)",
    )
    parser.add_argument(
        "--expect-full-hash",
        action="store_true",
        help="Require DEVELOPMENT_DATASET_V1 SHA-256 of the full 1000-claim ZIP",
    )
    args = parser.parse_args()

    if bool(args.url) == bool(args.reassemble_dir):
        raise SystemExit("Provide exactly one of --url or --reassemble-dir")

    dest = args.output or (DEFAULT_OPS_OUT if args.as_ops_subset else DEFAULT_FULL_OUT)
    if args.url:
        _download(args.url, dest)
    else:
        _reassemble(args.reassemble_dir, dest)

    digest = _sha256(dest)
    print(f"SHA-256: {digest}")
    if args.expect_full_hash and digest != EXPECTED_FULL_SHA256:
        raise SystemExit(
            "Hash mismatch for full Hackathon archive; "
            f"expected {EXPECTED_FULL_SHA256}"
        )
    if args.as_ops_subset:
        _write_ops_yaml(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
