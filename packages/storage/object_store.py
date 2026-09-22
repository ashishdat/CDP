"""S3-compatible object storage (MinIO locally, any S3-compatible endpoint
in prod). Keys are content-addressed so exact-duplicate uploads are
naturally deduplicated at the storage layer as well as the DB layer.

For Docker-less local UI demos, set ``OBJECT_STORE_BACKEND=filesystem`` and
``OBJECT_STORE_FILESYSTEM_ROOT`` to a writable directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import boto3
from botocore.client import Config as BotoConfig

from packages.domain.common import ObjectRef
from packages.storage.hashing import sha256_bytes

DEFAULT_SIGNED_URL_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class ObjectStoreSettings:
    endpoint_url: str
    access_key: str
    secret_key: str
    region: str = "us-east-1"
    use_ssl: bool = False


def content_addressed_key(sha256_hex: str, filename: str) -> str:
    """documents/{sha2}/{sha2..4}/{sha2}_{original filename}"""
    suffix = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return f"documents/{sha256_hex[:2]}/{sha256_hex[2:4]}/{sha256_hex}_{suffix}"


class ObjectStoreProtocol(Protocol):
    def ensure_bucket(self, bucket: str) -> None: ...

    def put_immutable(
        self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectRef: ...

    def get_bytes(self, ref: ObjectRef) -> bytes: ...

    def delete_object(self, bucket: str, key: str) -> None: ...

    def exists(self, bucket: str, key: str) -> bool: ...

    def signed_get_url(
        self, ref: ObjectRef, ttl: timedelta = DEFAULT_SIGNED_URL_TTL
    ) -> str: ...


class ObjectStore:
    def __init__(self, settings: ObjectStoreSettings) -> None:
        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            region_name=settings.region,
            use_ssl=settings.use_ssl,
            config=BotoConfig(signature_version="s3v4"),
        )

    def ensure_bucket(self, bucket: str) -> None:
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if bucket not in existing:
            self._client.create_bucket(Bucket=bucket)

    def put_immutable(
        self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectRef:
        """Write-once semantics enforced at the app layer: callers must
        derive `key` from content hash (see `content_addressed_key`), so a
        re-put of the same bytes is a no-op overwrite of identical content,
        never a mutation of different content under the same key."""
        digest = sha256_bytes(data)
        self._client.put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=content_type
        )
        return ObjectRef(
            bucket=bucket,
            key=key,
            content_type=content_type,
            sha256=digest,
            size_bytes=len(data),
        )

    def get_bytes(self, ref: ObjectRef) -> bytes:
        response = self._client.get_object(Bucket=ref.bucket, Key=ref.key)
        return response["Body"].read()

    def delete_object(self, bucket: str, key: str) -> None:
        """Implements `packages.security.retention.ObjectDeleter`. Used only
        by the retention/deletion workflow -- everywhere else, objects are
        immutable (see `put_immutable`)."""
        self._client.delete_object(Bucket=bucket, Key=key)

    def exists(self, bucket: str, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def signed_get_url(
        self, ref: ObjectRef, ttl: timedelta = DEFAULT_SIGNED_URL_TTL
    ) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": ref.bucket, "Key": ref.key},
            ExpiresIn=int(ttl.total_seconds()),
        )


class FilesystemObjectStore:
    """Local disk object store for Docker-less UI / API demos."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        safe_key = key.lstrip("/")
        path = (self._root / bucket / safe_key).resolve()
        if not str(path).startswith(str(self._root)):
            raise ValueError("object key escapes filesystem root")
        return path

    def ensure_bucket(self, bucket: str) -> None:
        (self._root / bucket).mkdir(parents=True, exist_ok=True)

    def put_immutable(
        self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectRef:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        meta = path.with_suffix(path.suffix + ".content_type")
        meta.write_text(content_type, encoding="utf-8")
        digest = sha256_bytes(data)
        return ObjectRef(
            bucket=bucket,
            key=key,
            content_type=content_type,
            sha256=digest,
            size_bytes=len(data),
        )

    def get_bytes(self, ref: ObjectRef) -> bytes:
        return self._path(ref.bucket, ref.key).read_bytes()

    def delete_object(self, bucket: str, key: str) -> None:
        path = self._path(bucket, key)
        if path.exists():
            path.unlink()
        meta = path.with_suffix(path.suffix + ".content_type")
        if meta.exists():
            meta.unlink()

    def exists(self, bucket: str, key: str) -> bool:
        return self._path(bucket, key).is_file()

    def signed_get_url(
        self, ref: ObjectRef, ttl: timedelta = DEFAULT_SIGNED_URL_TTL
    ) -> str:
        del ttl  # local demo URLs are path-based, not time-limited
        return f"file://{quote(str(self._path(ref.bucket, ref.key)))}"


def build_object_store(
    *,
    backend: str = "s3",
    filesystem_root: str = "/tmp/idp-objects",
    settings: ObjectStoreSettings | None = None,
) -> ObjectStoreProtocol:
    """Construct the configured object store implementation."""
    kind = (backend or "s3").strip().casefold()
    if kind in {"filesystem", "fs", "local"}:
        return FilesystemObjectStore(filesystem_root)
    if settings is None:
        raise ValueError("S3 object store requires ObjectStoreSettings")
    return ObjectStore(settings)
