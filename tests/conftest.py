"""Shared test fixtures.

`FakeObjectStore` duck-types `packages.storage.object_store.ObjectStore`'s
public surface (put_immutable/get_bytes/exists/signed_get_url) without
talking to real S3/MinIO, so Phase 1 unit tests don't require Docker.
Integration tests that must exercise the real MinIO/Postgres/Redpanda
stack are marked `@pytest.mark.integration` and skipped by default (see
docs/ARCHITECTURE.md and the Makefile `test-integration` target).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.domain.common import ObjectRef
from packages.storage.hashing import sha256_bytes

DATASET_RAW_DIR = Path(__file__).resolve().parent.parent / "dataset_raw"


def dataset_available() -> bool:
    return DATASET_RAW_DIR.is_dir()


requires_dataset = pytest.mark.skipif(
    not dataset_available(),
    reason="dataset_raw/ (extracted 'Images & Output.zip') not present on this machine",
)


class FakeObjectStore:
    """In-memory stand-in for `packages.storage.object_store.ObjectStore`."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], bytes] = {}

    def ensure_bucket(self, bucket: str) -> None:
        pass

    def put_immutable(
        self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectRef:
        self._objects[(bucket, key)] = data
        return ObjectRef(
            bucket=bucket,
            key=key,
            content_type=content_type,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
        )

    def get_bytes(self, ref: ObjectRef) -> bytes:
        return self._objects[(ref.bucket, ref.key)]

    def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self._objects

    def signed_get_url(self, ref: ObjectRef, ttl=None) -> str:
        return f"https://fake-object-store.local/{ref.bucket}/{ref.key}?signed=1"


@pytest.fixture
def fake_object_store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def dataset_raw_dir() -> Path:
    return DATASET_RAW_DIR
