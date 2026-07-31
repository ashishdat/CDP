"""Append-only, local correction sink for supervised retraining data."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CorrectionExample:
    document_id: str
    field_name: str
    previous_value: str | None
    corrected_value: str
    crop_reference: str | None
    reviewer: str
    corrected_at: str


class CorrectionSink(Protocol):
    def append(self, example: CorrectionExample) -> None: ...


class JsonlCorrectionSink:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, example: CorrectionExample) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(example), ensure_ascii=False) + "\n")


def correction_example(
    document_id: str,
    field_name: str,
    previous_value: str | None,
    corrected_value: str,
    crop_reference: str | None,
    reviewer: str,
) -> CorrectionExample:
    return CorrectionExample(
        document_id, field_name, previous_value, corrected_value, crop_reference,
        reviewer, datetime.now(UTC).isoformat(),
    )
