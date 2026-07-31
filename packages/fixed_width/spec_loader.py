"""Loads `FixedWidthRecordSpec`s from `config/output_specs/{nsf,ub92}/*.yaml`
-- one file per record type. Adding a record type or correcting a field
position is a config change (see docs/CONFIGURATION_GUIDE.md), never code.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from packages.fixed_width.spec_models import FixedWidthRecordSpec

CONFIG_OUTPUT_SPECS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "config" / "output_specs"
)


def load_record_specs(directory: Path) -> dict[str, FixedWidthRecordSpec]:
    specs: dict[str, FixedWidthRecordSpec] = {}
    for path in sorted(directory.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        spec = FixedWidthRecordSpec.model_validate(data)
        specs[spec.record_type] = spec
    return specs


def load_nsf_specs() -> dict[str, FixedWidthRecordSpec]:
    return load_record_specs(CONFIG_OUTPUT_SPECS_DIR / "nsf")


def load_ub92_specs() -> dict[str, FixedWidthRecordSpec]:
    return load_record_specs(CONFIG_OUTPUT_SPECS_DIR / "ub92")
