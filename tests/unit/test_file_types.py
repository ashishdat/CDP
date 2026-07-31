"""File signature (magic-byte) detection — never trusts extensions."""

from packages.domain.enums import SourceFormat
from packages.storage.file_types import detect_file_type, sniff_format
from tests.conftest import requires_dataset


def test_detects_little_endian_tiff():
    head = b"\x49\x49\x2a\x00" + b"\x00" * 12
    assert sniff_format(head) == SourceFormat.TIFF


def test_detects_big_endian_tiff():
    head = b"\x4d\x4d\x00\x2a" + b"\x00" * 12
    assert sniff_format(head) == SourceFormat.TIFF


def test_detects_pdf():
    assert sniff_format(b"%PDF-1.7\n%...") == SourceFormat.PDF


def test_detects_png():
    head = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    assert sniff_format(head) == SourceFormat.PNG


def test_detects_jpeg():
    head = b"\xff\xd8\xff\xe0" + b"\x00" * 12
    assert sniff_format(head) == SourceFormat.JPEG


def test_unknown_format_is_not_supported():
    result = detect_file_type(b"not an image at all")
    assert result.format == SourceFormat.UNKNOWN
    assert result.is_supported is False


def test_extension_is_never_consulted():
    """A `.txt`-named blob with TIFF magic bytes must still be detected as
    TIFF — this is the entire point of the requirement."""
    head = b"\x49\x49\x2a\x00" + b"\x00" * 12
    result = detect_file_type(head)
    assert result.format == SourceFormat.TIFF
    assert result.is_tiff


@requires_dataset
def test_every_sample_numbered_file_is_tiff(dataset_raw_dir):
    """Regression test against the real supplied dataset: every `.001`,
    `.002`, ... file across all four groups is TIFF by magic bytes,
    regardless of its non-standard extension (see
    docs/DATASET_FINDINGS.md)."""

    numbered_files = [
        p
        for group in sorted(dataset_raw_dir.glob("Group *"))
        for p in sorted(group.glob("*.0*"))
    ]
    assert len(numbered_files) == 30  # 12 + 5 + 6 + 7
    for path in numbered_files:
        with open(path, "rb") as f:
            head = f.read(16)
        result = detect_file_type(head)
        assert result.is_tiff, f"{path} was not detected as TIFF"
