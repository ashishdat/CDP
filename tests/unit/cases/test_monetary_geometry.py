"""Geometry dollars|cents reconstruction and Self name agreement."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from packages.geometry_authority.form_redundancy import (
    names_agree,
    prefer_fuller_self_name,
    promote_fuller_observed_name,
    reconcile_box2_box4_names,
)
from packages.geometry_authority.monetary_geometry import (
    GlyphBox,
    reconstruct_from_glyphs,
)


def _glyph(char: str, x0: int, x1: int) -> GlyphBox:
    return GlyphBox(char, x0, 0, x1, 12)


def test_one_line_whole_dollars_across_ruling():
    glyphs = [
        _glyph("2", 10, 18),
        _glyph("7", 20, 28),
        _glyph("0", 30, 38),
        _glyph("0", 70, 78),
        _glyph("0", 80, 88),
    ]
    read = reconstruct_from_glyphs(glyphs, ruling_x=55)
    assert read.ambiguous is False
    assert read.geometry_candidate == "270.00"
    assert read.dollars == "270"


def test_spatial_cents_not_thousands():
    glyphs = [
        _glyph("4", 10, 18),
        _glyph("9", 20, 28),
        _glyph("7", 60, 68),
        _glyph("2", 70, 78),
    ]
    read = reconstruct_from_glyphs(glyphs, ruling_x=45)
    assert read.geometry_candidate == "49.72"
    assert read.ambiguous is False


def test_four_digits_without_ruling_stay_ambiguous():
    glyphs = [_glyph(c, i * 10, i * 10 + 8) for i, c in enumerate("4972")]
    read = reconstruct_from_glyphs(glyphs, ruling_x=None)
    assert read.ambiguous is True
    assert read.geometry_candidate is None


def test_units_bleed_third_cent_is_ambiguous():
    glyphs = [
        _glyph("2", 10, 18),
        _glyph("7", 20, 28),
        _glyph("0", 30, 38),
        _glyph("0", 60, 68),
        _glyph("0", 70, 78),
        _glyph("1", 82, 90),
    ]
    read = reconstruct_from_glyphs(glyphs, ruling_x=50)
    assert read.ambiguous is True
    assert read.geometry_candidate is None


def test_box29_glyphs_right_of_crop_are_not_included():
    # Caller must crop before Box 29. A ruling inside the crop still splits 200.00.
    glyphs = [_glyph("2", 4, 12), _glyph("0", 14, 22), _glyph("0", 24, 32)]
    read = reconstruct_from_glyphs(glyphs, ruling_x=40)
    assert read.geometry_candidate == "200.00"


def test_multiple_lines_sum_matches_box28_representation():
    line_a = reconstruct_from_glyphs(
        [_glyph("1", 2, 8), _glyph("3", 10, 16), _glyph("5", 18, 24)],
        ruling_x=40,
    )
    line_b = reconstruct_from_glyphs(
        [_glyph("1", 2, 8), _glyph("3", 10, 16), _glyph("5", 18, 24)],
        ruling_x=40,
    )
    total = reconstruct_from_glyphs(
        [_glyph("2", 2, 8), _glyph("7", 10, 16), _glyph("0", 18, 24)],
        ruling_x=40,
    )
    assert line_a.geometry_candidate == "135.00"
    assert total.geometry_candidate == "270.00"
    from decimal import Decimal

    assert Decimal(line_a.geometry_candidate) + Decimal(line_b.geometry_candidate) == Decimal(
        total.geometry_candidate
    )


def test_self_name_punctuation_and_multi_token_surname():
    assert names_agree("SAN NICOLAS, WILLIAM", "SAN NICOLAS. WILLIAM")
    assert names_agree("MORALES, KENITHA", "MORALES KENITHA")
    agreed = reconcile_box2_box4_names(
        "SAN NICOLAS, WILLIAM", "San Nicolas. William", relationship="SELF"
    )
    assert agreed.agreed
    disagree = reconcile_box2_box4_names(
        "MORALES, KENITHA", "SAN NICOLAS, WILLIAM", relationship="SELF"
    )
    assert not disagree.agreed
    non_self = reconcile_box2_box4_names(
        "MORALES, KENITHA", "MORALES, KENITHA", relationship="SPOUSE"
    )
    assert not non_self.agreed
    assert non_self.reason == "RELATIONSHIP_NOT_SELF"


def test_promote_fuller_observed_name_keeps_raw_under_self_only():
    promoted = promote_fuller_observed_name(
        "NICOLAS, WILLIAM",
        "SAN NICOLAS, WILLIAM",
        "SAN NICOLAS. WILLIAM",
        "SELF",
    )
    assert promoted == "SAN NICOLAS, WILLIAM"
    # Punctuation-only twins are not a longer name.
    assert (
        promote_fuller_observed_name(
            "MORALES, KENITHA",
            "MORALES. KENITHA",
            "MORALES, KENITHA",
            "SELF",
        )
        == "MORALES, KENITHA"
    )
    # Disagreement stays on the candidate that was actually read.
    assert (
        promote_fuller_observed_name(
            "NICOLAS, WILLIAM",
            "SAN NICOLAS, WILLIAM",
            "JONES, WILLIAM",
            "SELF",
        )
        == "NICOLAS, WILLIAM"
    )
    # Non-Self must not force Box 2 to equal Box 4.
    assert (
        promote_fuller_observed_name(
            "RIVERA, LARAA",
            "RIVERA, LARAA ANDREW",
            "RIVERA, ANDREW",
            "SPOUSE",
        )
        == "RIVERA, LARAA"
    )


def test_prefer_fuller_observed_self_name_does_not_invent():
    chosen = prefer_fuller_self_name(
        ["NICOLAS, WILLIAM", "SAN NICOLAS.WILLIAM"],
        "SAN NICOLAS, WILLIAM",
    )
    assert chosen == "SAN NICOLAS.WILLIAM"
    assert (
        prefer_fuller_self_name(["NICOLAS, WILLIAM"], "SAN NICOLAS, WILLIAM") is None
    )


def test_synthetic_value_band_excludes_caption_row():
    from packages.geometry_authority.monetary_geometry import locate_value_band

    img = Image.new("L", (120, 48), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((4, 2, 80, 10), fill=0)
    draw.rectangle((40, 28, 90, 40), fill=0)
    y0, y1 = locate_value_band(np.asarray(img))
    assert y0 >= 20
    assert y1 > y0


def test_token_assembly_visible_decimal_and_left_digit():
    from packages.geometry_authority.monetary_geometry import TextToken, assemble_printed_tokens

    read = assemble_printed_tokens(
        [
            TextToken("4", 10, 0, 22, 12),
            TextToken("9.72", 24, 0, 70, 12),
        ],
        ruling_x=40,
        geometry_authorised=True,
    )
    assert read.geometry_candidate == "49.72"
    assert read.decimal_visible is True
    assert read.ambiguous is False


def test_token_assembly_cents_column_and_confusable():
    from packages.geometry_authority.monetary_geometry import TextToken, assemble_printed_tokens

    split = assemble_printed_tokens(
        [TextToken("270", 10, 0, 40, 12), TextToken("00", 44, 0, 70, 12)],
        ruling_x=42,
        geometry_authorised=True,
    )
    assert split.geometry_candidate == "270.00"
    confusable = assemble_printed_tokens(
        [TextToken("60q.00", 10, 0, 80, 12)],
        ruling_x=50,
        geometry_authorised=True,
    )
    assert confusable.geometry_candidate == "600.00"
    units = assemble_printed_tokens(
        [TextToken("270.00", 10, 0, 60, 12), TextToken("1", 70, 0, 80, 12)],
        ruling_x=48,
        geometry_authorised=True,
    )
    assert units.ambiguous is True
    assert units.geometry_candidate is None


def test_glyph_gap_implies_cents_not_thousands():
    from packages.geometry_authority.monetary_geometry import split_digit_glyphs

    glyphs = [
        _glyph("4", 10, 18),
        _glyph("9", 24, 32),
        _glyph("7", 40, 48),
        _glyph("2", 52, 60),
    ]
    read = split_digit_glyphs(glyphs)
    assert read.geometry_candidate == "49.72"
    short = split_digit_glyphs([_glyph("2", 10, 18), _glyph("1", 28, 36), _glyph("2", 40, 48)])
    assert short.ambiguous is True
    assert short.geometry_candidate is None

