"""Preprocessing primitives: orientation, deskew, denoise, thumbnailing."""

from PIL import Image, ImageDraw

from workers.document_preparation.preprocessing import (
    apply_orientation,
    deskew,
    detect_orientation,
    detect_skew_angle,
    make_thumbnail,
)


def _text_like_image(width=400, height=300) -> Image.Image:
    """A synthetic image with strong horizontal "text line" structure."""
    img = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(img)
    for y in range(20, height - 20, 20):
        draw.rectangle([20, y, width - 20, y + 8], fill=0)
    return img


def test_detect_orientation_returns_a_valid_rotation_bucket():
    img = _text_like_image()
    assert detect_orientation(img) in (0, 90, 180, 270)


def test_detect_orientation_prefers_upright_over_sideways():
    img = _text_like_image(400, 300)
    rotation = detect_orientation(img)
    # horizontal line structure -> should NOT prefer a 90/270 (sideways) read
    assert rotation in (0, 180)


def test_apply_orientation_zero_is_identity():
    img = _text_like_image()
    assert apply_orientation(img, 0) is img


def test_apply_orientation_ninety_swaps_dimensions():
    img = _text_like_image(400, 300)
    rotated = apply_orientation(img, 90)
    assert rotated.size == (300, 400)


def test_detect_skew_angle_on_axis_aligned_image_is_small():
    img = _text_like_image()
    angle = detect_skew_angle(img)
    assert abs(angle) < 5.0


def test_deskew_zero_angle_is_identity():
    img = _text_like_image()
    assert deskew(img, 0.0) is img


def test_deskew_nonzero_angle_returns_same_size_image():
    img = _text_like_image()
    result = deskew(img, 3.0)
    assert result.size == img.size


def test_make_thumbnail_respects_max_dimension():
    img = _text_like_image(1200, 900)
    thumb = make_thumbnail(img, max_dimension=300)
    assert max(thumb.size) <= 300
    # aspect ratio preserved
    assert round(thumb.size[0] / thumb.size[1], 2) == round(1200 / 900, 2)
