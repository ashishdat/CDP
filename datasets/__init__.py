"""Dataset registration and read-only corpus verification."""

from .registry import REGISTRY, DatasetManager, DatasetMetadata, DatasetType

__all__ = ["REGISTRY", "DatasetManager", "DatasetMetadata", "DatasetType"]
