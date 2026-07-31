from __future__ import annotations

from pathlib import Path

import yaml

from .models import RecordDefinition


class SpecificationRegistry:
    def __init__(self, root: Path = Path("config/output_specs")) -> None:
        self.root = root

    def load(self, format_name: str, record_type: str) -> RecordDefinition:
        path = self.root / format_name.lower() / "compiled" / f"{record_type}.yaml"
        return RecordDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def load_all(self, format_name: str) -> dict[str, RecordDefinition]:
        directory = self.root / format_name.lower() / "compiled"
        return {
            path.stem: RecordDefinition.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            )
            for path in sorted(directory.glob("*.yaml"))
        }
