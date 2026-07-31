"""Object storage, hashing, and dependency-free magic-byte file typing."""

from packages.storage.file_types import FileTypeResult, detect_file_type, sniff_format
from packages.storage.hashing import hamming_distance, perceptual_hash, sha256_bytes, sha256_file
from packages.storage.object_store import ObjectStore, ObjectStoreSettings, content_addressed_key

__all__ = [
    "FileTypeResult",
    "ObjectStore",
    "ObjectStoreSettings",
    "content_addressed_key",
    "detect_file_type",
    "hamming_distance",
    "perceptual_hash",
    "sha256_bytes",
    "sha256_file",
    "sniff_format",
]
