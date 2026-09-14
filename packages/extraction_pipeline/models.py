"""Immutable orchestration configuration; business models stay in their owners."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class FeatureFlag(StrEnum):
    PIPELINE_V3 = "PIPELINE_V3"
    GEOMETRY_V3 = "GEOMETRY_V3"
    OCR_ROUTER_V3 = "OCR_ROUTER_V3"
    VALIDATOR_V3 = "VALIDATOR_V3"


@dataclass(frozen=True)
class FeatureFlags:
    enabled: frozenset[FeatureFlag] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", frozenset(FeatureFlag(v) for v in self.enabled))

    def allows(self, flag: FeatureFlag) -> bool:
        return flag in self.enabled

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "FeatureFlags":
        """Parse a caller-provided environment snapshot; never read global state."""
        enabled = set()
        for flag in FeatureFlag:
            value = values.get(flag.value, "false").strip().lower()
            if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                raise ValueError(f"Invalid boolean for {flag.value}")
            if value in {"true", "1", "yes", "on"}:
                enabled.add(flag)
        return cls(frozenset(enabled))
