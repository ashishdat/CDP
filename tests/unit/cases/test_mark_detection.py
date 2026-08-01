from PIL import Image, ImageDraw

from workers.field_candidates.mark_detection import detect_option_mark


def test_mark_detector_removes_baseline_and_requires_margin():
    blank = Image.new("L", (100, 30), 255)
    observed = blank.copy()
    ImageDraw.Draw(observed).rectangle((12, 7, 25, 20), fill=0)
    result = detect_option_mark(
        observed,
        {"SELF": (10, 5, 28, 23), "SPOUSE": (50, 5, 68, 23)},
        blank_reference=blank,
        border_inset=2,
    )
    assert result.selected_option == "SELF"
    assert result.winning_margin > 0
    assert result.method == "PIXEL_MARK_DETECTION"


def test_multiple_marks_are_ambiguous():
    image = Image.new("L", (100, 30), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 7, 25, 20), fill=0)
    draw.rectangle((52, 7, 65, 20), fill=0)
    result = detect_option_mark(
        image, {"SELF": (10, 5, 28, 23), "SPOUSE": (50, 5, 68, 23)}
    )
    assert result.ambiguous
    assert result.failure_reason == "AMBIGUOUS_MARK"
