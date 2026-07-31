"""TIFF (including multipage Group-4) and PDF page decoding.

Both codecs produce a common `DecodedPage` so everything downstream
(preprocessing, classification, OCR) is format-agnostic once a document has
been decoded. TIFF decode goes through Pillow (bundled libtiff, CCITT
Group-4/T.6 support confirmed against the real project dataset — see
docs/DATASET_FINDINGS.md). PDF decode goes through PyMuPDF.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import fitz  # PyMuPDF
from PIL import Image

from packages.domain.enums import CompressionType
from packages.storage.file_types import compression_from_tiff_tag

PDF_RASTER_DPI = 200  # matches the ~200 DPI of the supplied TIFF dataset


@dataclass
class DecodedPage:
    page_number: int  # 1-indexed
    image: Image.Image
    width_px: int
    height_px: int
    compression: CompressionType


class UnsupportedDocumentError(ValueError):
    pass


def decode_tiff_pages(data: bytes) -> list[DecodedPage]:
    pages: list[DecodedPage] = []
    with Image.open(io.BytesIO(data)) as im:
        if im.format != "TIFF":
            raise UnsupportedDocumentError(f"expected TIFF, got {im.format}")
        n_frames = getattr(im, "n_frames", 1)
        for i in range(n_frames):
            im.seek(i)
            width, height = im.size
            compression_tag = im.tag_v2.get(259) if hasattr(im, "tag_v2") else None
            compression = (
                compression_from_tiff_tag(int(compression_tag))
                if compression_tag is not None
                else CompressionType.OTHER
            )
            # .copy() detaches the frame from the lazily-seeking file handle
            pages.append(
                DecodedPage(
                    page_number=i + 1,
                    image=im.convert("L").copy(),
                    width_px=width,
                    height_px=height,
                    compression=compression,
                )
            )
    return pages


def decode_pdf_pages(data: bytes, dpi: int = PDF_RASTER_DPI) -> list[DecodedPage]:
    pages: list[DecodedPage] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
            image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
            pages.append(
                DecodedPage(
                    page_number=i + 1,
                    image=image,
                    width_px=pixmap.width,
                    height_px=pixmap.height,
                    compression=CompressionType.UNCOMPRESSED,
                )
            )
    return pages
