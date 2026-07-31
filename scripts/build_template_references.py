"""Create local, PHI-bearing template references from representative scans.

Outputs are gitignored. They are runtime calibration artifacts and must be
protected with the same controls as the source claims.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageSequence

REFERENCES = {
    "cms1500_v02_12.png": Path("Group A/M047FJFL.001"),
    "ub04_v2014.png": Path("Group C/M047IJBF.001"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("config/templates/reference_images")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for output_name, relative_source in REFERENCES.items():
        source = args.dataset / relative_source
        with Image.open(source) as image:
            first_page = next(ImageSequence.Iterator(image)).convert("L")
            target = args.output / output_name
            first_page.save(target, format="PNG", optimize=True)
            print(f"Wrote {target} from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
