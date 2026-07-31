from PIL import Image

from workers.page_detection.text_extraction import TextLine
from workers.unstructured_extraction.anchor_cropper import extract_anchor_crops
from workers.unstructured_extraction.family_router import DocumentFamilyRouter


def _line(text, x0=10, y0=10, x1=100, y1=30, confidence=.9):
    return TextLine(text, x0, y0, x1, y1, confidence)


def test_router_selects_relevant_page_and_family_not_first_page():
    router = DocumentFamilyRouter({
        "families": {
            "receipt": {"required_any": ["client name", "psychological services"]},
            "lab": {"required_any": ["laboratory bill", "quest diagnostics"]},
        }
    })
    decision = router.route({
        1: [_line("Document Separator")],
        2: [_line("Receipt for Psychological Services"), _line("Client Name")],
    })
    assert decision.family == "receipt"
    assert decision.page_number == 2
    assert not decision.needs_review


def test_anchor_crop_is_relative_to_detected_label():
    page = Image.new("RGB", (600, 400), "white")
    crops = extract_anchor_crops(
        page,
        [_line("Client:", 20, 100, 100, 125)],
        {"patient_name": {
            "anchors": ["client:"], "direction": "right_or_below",
            "width_px": 300, "height_px": 60,
        }},
    )
    assert crops["patient_name"].box == (108, 100, 408, 160)
