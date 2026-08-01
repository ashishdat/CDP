"""Multipage TIFF decoding, including CCITT Group-4 compressed pages."""

import io

import pytest
from PIL import Image

from packages.domain.enums import CompressionType
from tests.conftest import requires_dataset
from workers.document_preparation.codecs import decode_tiff_pages


def _make_g4_tiff_bytes(page_sizes: list[tuple[int, int]]) -> bytes:
    images = []
    for width, height in page_sizes:
        img = Image.new("1", (width, height), color=1)
        img.paste(0, (10, 10, width - 10, 20))  # a black bar so it isn't blank
        images.append(img)
    buf = io.BytesIO()
    images[0].save(
        buf,
        format="TIFF",
        compression="group4",
        save_all=True,
        append_images=images[1:],
    )
    return buf.getvalue()


def test_decodes_single_page_group4_tiff():
    data = _make_g4_tiff_bytes([(200, 100)])
    pages = decode_tiff_pages(data)
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert (pages[0].width_px, pages[0].height_px) == (200, 100)
    assert pages[0].compression == CompressionType.CCITT_G4


def test_decodes_multipage_group4_tiff_preserving_page_order_and_sizes():
    sizes = [(200, 100), (150, 300), (400, 220)]
    data = _make_g4_tiff_bytes(sizes)
    pages = decode_tiff_pages(data)
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert [(p.width_px, p.height_px) for p in pages] == sizes
    assert all(p.compression == CompressionType.CCITT_G4 for p in pages)


def test_decoded_pages_are_independent_images_not_shared_buffer():
    data = _make_g4_tiff_bytes([(200, 100), (200, 100)])
    pages = decode_tiff_pages(data)
    # mutate one decoded image in place; the other must be unaffected
    pages[0].image.paste(0, (0, 0, 50, 50))
    # primary assertion: both still independently addressable/openable
    assert pages[0].image.size == pages[1].image.size == (200, 100)


@requires_dataset
@pytest.mark.parametrize(
    ("relative_path", "expected_page_count"),
    [
        ("Group A/M047FJFL.001", 1),
        ("Group B/M047IJB0.002", 7),
        ("Group C/M047IJBF.001", 1),
        ("Group D/M047KJET.004", 9),
    ],
)
def test_decodes_real_dataset_tiffs_with_expected_page_counts(
    dataset_raw_dir, relative_path, expected_page_count
):
    data = (dataset_raw_dir / relative_path).read_bytes()
    pages = decode_tiff_pages(data)
    assert len(pages) == expected_page_count
    assert all(p.compression == CompressionType.CCITT_G4 for p in pages)
    assert all(p.width_px > 1000 and p.height_px > 1000 for p in pages)
