"""Convert legacy Word specs and compile deterministic fixed-width YAML schemas."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from packages.specification_registry import LegacyClaimSpecParser, compile_specification


def convert_doc_to_text(source: Path) -> str:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable is None:
        sibling = source.with_name(
            "NSF_matrix.txt" if "NSF" in source.name.upper() else "UB92_specs.txt"
        )
        if sibling.is_file():
            return sibling.read_text(encoding="utf-8")
        raise RuntimeError("LibreOffice is required to convert legacy .doc specifications")
    with tempfile.TemporaryDirectory(prefix="claims-spec-") as temporary:
        root = Path(temporary)
        profile = root / "profile"
        output = root / "output"
        output.mkdir()
        subprocess.run(
            [
                executable,
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--headless",
                "--convert-to",
                "txt:Text",
                "--outdir",
                os.fspath(output),
                os.fspath(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        converted = output / f"{source.stem}.txt"
        if not converted.is_file():
            raise RuntimeError(f"LibreOffice did not produce {converted}")
        return converted.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument("--output", type=Path, default=Path("config/output_specs"))
    parser.add_argument(
        "--review-output", type=Path, default=Path("evaluation_results/specification_review")
    )
    args = parser.parse_args()
    definitions = [
        ("nsf", "002.15", 320, args.dataset / "NSF Matrix Version 2 15 - June 2013.doc"),
        ("ub92", "510", 192, args.dataset / "UB92 File Specs - February 2012.doc"),
    ]
    claim_parser = LegacyClaimSpecParser()
    for name, version, length, source in definitions:
        text = convert_doc_to_text(source)
        compiled = claim_parser.parse(
            text,
            format_name=name,
            version=version,
            source_document=source.name,
            record_length=length,
        )
        generated = compile_specification(
            compiled,
            args.output / name / "compiled",
            args.review_output / f"{name}.yaml",
        )
        print(
            f"{name}: {len(compiled.records)} records, "
            f"{sum(len(record.fields) for record in compiled.records)} fields, "
            f"{len(generated)} schemas"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
