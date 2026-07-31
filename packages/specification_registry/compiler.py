from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import CompiledSpecification
from .validator import validate_specification


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value or "unnamed"


def compile_specification(
    specification: CompiledSpecification,
    output_dir: Path,
    review_report: Path,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for record in specification.records:
        payload = record.model_dump(mode="json")
        for field in payload["fields"]:
            field["canonical_name"] = _slug(field["field_name"])
        target = output_dir / f"{record.record_type}.yaml"
        target.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        generated.append(target)
    issues = validate_specification(specification)
    review_report.parent.mkdir(parents=True, exist_ok=True)
    review_report.write_text(
        yaml.safe_dump(
            {
                "format": specification.format_name,
                "version": specification.version,
                "source_document": specification.source_document,
                "record_count": len(specification.records),
                "field_count": sum(len(record.fields) for record in specification.records),
                "issues": [issue.model_dump(mode="json") for issue in issues],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return generated

