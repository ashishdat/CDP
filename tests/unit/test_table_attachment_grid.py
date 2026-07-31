from PIL import Image

from workers.page_detection.text_extraction import TextLine
from workers.table_extraction.attachment_grid import extract_attachment_grid


def test_lab_grid_requires_layout_anchors(monkeypatch):
    monkeypatch.setattr(
        "workers.table_extraction.attachment_grid.TesseractTextExtractor.extract",
        lambda self, image: [],
    )
    result = extract_attachment_grid(
        Image.new("RGB", (1700, 2200), "white"), "laboratory_invoice"
    )
    assert result.grid is None
    assert result.failure_reason == "ANCHOR_VARIANT_MISMATCH"


def test_statement_grid_uses_named_nonoverlapping_cells(monkeypatch):
    tokens = [
        TextLine("Receipt", 100, 100, 160, 120, 0.9),
        TextLine("&", 165, 100, 175, 120, 0.9),
        TextLine("Insurance", 180, 100, 260, 120, 0.9),
        TextLine("Statement", 265, 100, 350, 120, 0.9),
        TextLine("Date", 300, 900, 340, 920, 0.9),
        TextLine("of", 345, 900, 360, 920, 0.9),
        TextLine("Service", 365, 900, 430, 920, 0.9),
        TextLine("06/24/2026", 300, 1080, 430, 1100, 0.9),
    ]
    monkeypatch.setattr(
        "workers.table_extraction.attachment_grid.TesseractTextExtractor.extract",
        lambda self, image: tokens,
    )
    result = extract_attachment_grid(
        Image.new("RGB", (1700, 2200), "white"), "statement"
    )
    assert result.grid is not None
    assert len(result.grid.cells) == 21
    assert {cell.column_name for cell in result.grid.cells} == {
        "service_date", "fee_for_service", "cpt_code",
    }
