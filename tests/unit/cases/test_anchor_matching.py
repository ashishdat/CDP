"""Anchor-phrase matching logic, decoupled from any OCR engine."""

from packages.templates.models import AnchorDefinition, FieldRegion
from workers.page_detection.anchor_matching import verify_anchors
from workers.page_detection.text_extraction import TextLine


def _line(text: str, x0=0, y0=0, x1=100, y1=20) -> TextLine:
    return TextLine(text=text, x0=x0, y0=y0, x1=x1, y1=y1, confidence=0.95)


def test_all_required_anchors_matched():
    lines = [_line("HEALTH INSURANCE CLAIM FORM"), _line("PICA")]
    anchors = [
        AnchorDefinition(phrase="HEALTH INSURANCE CLAIM FORM"),
        AnchorDefinition(phrase="PICA"),
    ]
    result = verify_anchors(lines, anchors)
    assert result.all_required_matched
    assert result.confidence == 1.0
    assert result.missing_required == []


def test_missing_required_anchor_is_reported():
    lines = [_line("HEALTH INSURANCE CLAIM FORM")]
    anchors = [
        AnchorDefinition(phrase="HEALTH INSURANCE CLAIM FORM"),
        AnchorDefinition(phrase="PICA"),
    ]
    result = verify_anchors(lines, anchors)
    assert not result.all_required_matched
    assert result.missing_required == ["PICA"]
    assert result.confidence == 0.5


def test_optional_anchor_missing_does_not_block_all_required_matched():
    lines = [_line("HEALTH INSURANCE CLAIM FORM")]
    anchors = [
        AnchorDefinition(phrase="HEALTH INSURANCE CLAIM FORM", required=True),
        AnchorDefinition(phrase="FORM 1500", required=False),
    ]
    result = verify_anchors(lines, anchors)
    assert result.all_required_matched
    assert result.confidence == 0.5


def test_matching_is_case_and_whitespace_insensitive():
    lines = [_line("  health   insurance\nclaim form  ")]
    anchors = [AnchorDefinition(phrase="HEALTH INSURANCE CLAIM FORM")]
    result = verify_anchors(lines, anchors)
    assert result.all_required_matched


def test_wrong_form_text_does_not_match():
    lines = [_line("TYPE OF BILL"), _line("STATEMENT COVERS PERIOD")]
    anchors = [AnchorDefinition(phrase="HEALTH INSURANCE CLAIM FORM")]
    result = verify_anchors(lines, anchors)
    assert not result.all_required_matched
    assert result.confidence == 0.0


def test_no_anchor_definitions_yields_zero_confidence():
    result = verify_anchors([_line("anything")], [])
    assert result.confidence == 0.0
    assert result.all_required_matched  # vacuously true: nothing required


def test_region_scoped_anchor_only_matches_within_region():
    region = FieldRegion(field_name="header", x0=0, y0=0, x1=200, y1=50)
    anchors = [AnchorDefinition(phrase="PICA", region=region)]

    inside = [_line("PICA", x0=10, y0=10, x1=60, y1=30)]
    outside = [_line("PICA", x0=500, y0=900, x1=560, y1=920)]

    assert verify_anchors(inside, anchors).all_required_matched
    assert not verify_anchors(outside, anchors).all_required_matched
