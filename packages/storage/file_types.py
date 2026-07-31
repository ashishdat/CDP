"""Magic-byte file-type detection.

Deliberately dependency-free (no `python-magic`/`libmagic`, which isn't
reliably available on Windows dev machines) — only the first bytes of the
file are inspected. Verified against the real project dataset: every
supplied `.001`/`.002`/... file is a little-endian TIFF regardless of its
extension (see docs/DATASET_FINDINGS.md).

Extensions are NEVER consulted for format detection, per spec.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.domain.enums import CompressionType, SourceFormat

_TIFF_LE = b"\x49\x49\x2a\x00"  # "II*\0"
_TIFF_BE = b"\x4d\x4d\x00\x2a"  # "MM\0*"
_PDF = b"%PDF"
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"

_MAX_SNIFF_BYTES = 16

_COMPRESSION_NAMES = {
    1: CompressionType.UNCOMPRESSED,
    2: CompressionType.CCITT_G3,
    3: CompressionType.CCITT_G3,
    4: CompressionType.CCITT_G4,
    5: CompressionType.LZW,
    6: CompressionType.JPEG,
    7: CompressionType.JPEG,
    8: CompressionType.DEFLATE,
    32773: CompressionType.PACKBITS,
}


@dataclass(frozen=True)
class FileTypeResult:
    format: SourceFormat
    is_supported: bool

    @property
    def is_tiff(self) -> bool:
        return self.format == SourceFormat.TIFF


def sniff_format(head: bytes) -> SourceFormat:
    """Detect format from the first bytes of a file. `head` should be at
    least `_MAX_SNIFF_BYTES` bytes (fewer is fine; matches will just fail)."""

    if head.startswith((_TIFF_LE, _TIFF_BE)):
        return SourceFormat.TIFF
    if head.startswith(_PDF):
        return SourceFormat.PDF
    if head.startswith(_PNG):
        return SourceFormat.PNG
    if head.startswith(_JPEG):
        return SourceFormat.JPEG
    return SourceFormat.UNKNOWN


def detect_file_type(data: bytes) -> FileTypeResult:
    fmt = sniff_format(data[:_MAX_SNIFF_BYTES])
    return FileTypeResult(format=fmt, is_supported=fmt != SourceFormat.UNKNOWN)


def detect_file_type_from_path(path: str) -> FileTypeResult:
    with open(path, "rb") as f:
        head = f.read(_MAX_SNIFF_BYTES)
    return detect_file_type(head)


def compression_from_tiff_tag(tag_value: int) -> CompressionType:
    return _COMPRESSION_NAMES.get(tag_value, CompressionType.OTHER)
