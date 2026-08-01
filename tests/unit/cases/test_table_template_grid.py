from itertools import pairwise

from PIL import Image

from workers.table_extraction.template_grid import (
    _usable_token_text,
    extract_template_grid,
)


def test_cms_template_grid_has_semantic_nonoverlapping_cells(monkeypatch):
    monkeypatch.setattr(
        "workers.table_extraction.template_grid.TesseractTextExtractor.extract_region",
        lambda self, image, x0, y0, x1, y1: [],
    )
    grid = extract_template_grid(Image.new("RGB", (1712, 2214), "white"), "CMS1500")
    assert len(grid.cells) == 60
    first = [cell for cell in grid.cells if cell.row_index == 0]
    assert first[0].column_name == "date_from"
    assert first[-1].column_name == "rendering_provider_npi"
    assert all(left.bbox[2] <= right.bbox[0] for left, right in pairwise(first))


def test_ub04_template_grid_covers_22_rows_and_named_columns(monkeypatch):
    monkeypatch.setattr(
        "workers.table_extraction.template_grid.TesseractTextExtractor.extract_region",
        lambda self, image, x0, y0, x1, y1: [],
    )
    grid = extract_template_grid(Image.new("RGB", (1711, 2216), "white"), "UB04")
    assert len(grid.cells) == 154
    assert {cell.row_index for cell in grid.cells} == set(range(22))
    assert {cell.column_name for cell in grid.cells} == {
        "revenue_code", "description", "hcpcs_rate", "service_date",
        "service_units", "total_charges", "non_covered_charges",
    }
    assert min(cell.bbox[1] for cell in grid.cells) == 568
    assert max(cell.bbox[3] for cell in grid.cells) == 1275


def test_standard_grid_uses_shadow_boundaries(monkeypatch):
    monkeypatch.setattr(
        "workers.table_extraction.template_grid.TesseractTextExtractor.extract_region",
        lambda self, image, x0, y0, x1, y1: [],
    )
    cms = extract_template_grid(Image.new("RGB", (1712, 2214), "white"), "CMS1500")
    cms_first = {
        cell.column_name: cell.bbox for cell in cms.cells if cell.row_index == 0
    }
    assert cms_first["date_from"] == (70, 1408, 240, 1472)
    assert cms_first["charges"] == (1030, 1408, 1207, 1472)

    ub = extract_template_grid(Image.new("RGB", (1711, 2216), "white"), "UB04")
    ub_first = {
        cell.column_name: cell.bbox for cell in ub.cells if cell.row_index == 0
    }
    assert ub_first["hcpcs_rate"] == (613, 568, 910, 600)
    assert ub_first["total_charges"] == (1208, 568, 1406, 600)


def test_tesseract_transport_fragments_are_not_document_evidence():
    assert not _usable_token_text("5\t1\t1\t1\t2\t3\t1532\t35")
    assert not _usable_token_text("5 1 1 1 2 3 1532 35")
    assert _usable_token_text("0251")
