from pathlib import Path

from PIL import Image, ImageDraw

from workers.table_extraction.semantic_blank import detect_semantic_blank


def test_grid_fragments_do_not_create_a_value(tmp_path: Path):
    image = Image.new("L", (190, 56), "white")
    draw = ImageDraw.Draw(image)
    draw.line((76, 29, 78, 36), fill="black", width=1)
    draw.point((18, 32), fill="black")
    evidence = detect_semantic_blank(image)
    assert evidence.is_blank is True
    assert evidence.substantive_components == 0


def test_real_character_is_not_blank():
    image = Image.new("L", (100, 56), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 30, 43), fill="black")
    evidence = detect_semantic_blank(image)
    assert evidence.is_blank is False


def test_full_height_grid_rule_is_ignored():
    image = Image.new("L", (100, 30), "white")
    ImageDraw.Draw(image).line((55, 0, 55, 29), fill="black", width=2)
    evidence = detect_semantic_blank(image)
    assert evidence.is_blank is True
    assert evidence.ignored_rule_components == 1
