"""Runtime flag snapshot, separate from process-global environment state."""

from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class RuntimeFlags:
    pipeline_v3: bool = False
    pipeline_v3_shadow: bool = False
    geometry_v3: bool = False
    ocr_router_v3: bool = False
    candidate_ranking_v3: bool = False
    validators_v3: bool = False

    def __post_init__(self):
        if any(type(getattr(self, field.name)) is not bool for field in fields(self)):
            raise ValueError("Runtime flags must be booleans")

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "RuntimeFlags":
        parsed = {}
        for field in fields(cls):
            name = "FEATURE_" + field.name.upper()
            value = values.get(name, "false").strip().lower()
            if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                raise ValueError(f"Invalid boolean for {name}")
            parsed[field.name] = value in {"true", "1", "yes", "on"}
        return cls(**parsed)

    @property
    def mode(self) -> str:
        if self.pipeline_v3_shadow:
            return "shadow"
        return "v3" if self.pipeline_v3 else "legacy"
