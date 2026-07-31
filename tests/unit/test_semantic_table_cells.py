from PIL import Image, ImageDraw

from workers.table_extraction.semantic_cells import extract_semantic_rows


def test_ub04_semantic_cells_exclude_headers_and_generic_names():
    page = Image.new("RGB", (1711, 2216), "white")
    draw = ImageDraw.Draw(page)
    draw.text((40, 580), "0251", fill="black")
    draw.text((150, 580), "LAB SERVICE", fill="black")
    rows = extract_semantic_rows(page, "UB04")

    first = rows[0]
    assert first["row_status"] == "ACTIVE"
    assert {cell.form_locator for cell in first["cells"]} == {
        "FL42",
        "FL43",
        "FL44",
        "FL45",
        "FL46",
        "FL47",
        "FL48",
    }
    assert all(not cell.semantic_field_name.startswith("column_") for cell in first["cells"])
    assert all(cell.registered_bbox[1] >= 568 for cell in first["cells"])
    fl44 = next(cell for cell in first["cells"] if cell.form_locator == "FL44")
    fl45 = next(cell for cell in first["cells"] if cell.form_locator == "FL45")
    assert fl44.registered_bbox[2] <= fl45.registered_bbox[0]
    assert fl44.semantic_field_name == "hcpcs_rate_hipps_code"
    assert fl45.semantic_field_name == "service_date"


def test_completely_unused_fixed_row_is_excluded():
    rows = extract_semantic_rows(Image.new("RGB", (1712, 2214), "white"), "CMS1500")
    assert all(row["row_status"] == "UNUSED" for row in rows)


def test_grid_rules_alone_do_not_activate_a_row():
    page = Image.new("RGB", (1711, 2216), "white")
    draw = ImageDraw.Draw(page)
    draw.line((30, 568, 1603, 568), fill="black", width=2)
    draw.line((1208, 568, 1208, 600), fill="black", width=2)
    for y in range(570, 600, 6):
        draw.point((1406, y), fill="black")

    rows = extract_semantic_rows(page, "UB04")

    assert rows[0]["row_status"] == "UNUSED"
