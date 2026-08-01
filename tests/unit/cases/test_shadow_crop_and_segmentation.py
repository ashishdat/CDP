from PIL import Image, ImageDraw

from workers.cascade.line_segmentation import segment_text_lines


def test_multiline_crop_is_segmented_without_horizontal_resizing():
    image = Image.new("L", (100, 50), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 70, 12), fill="black")
    draw.rectangle((8, 30, 90, 38), fill="black")
    lines = segment_text_lines(image)
    assert len(lines) == 2
    assert all(line.width == image.width for line in lines)
