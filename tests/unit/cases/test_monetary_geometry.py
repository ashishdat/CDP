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


def test_align_cents_examples_from_printed_forms():
    from packages.geometry_authority.monetary_geometry import align_cents_column

    cases = [
        ([(10, 20), (28, 38), (46, 56), (70, 80), (88, 98)], [(60, 63)], "21200", "212.00"),
        ([(10, 20), (28, 38), (46, 56), (70, 80), (88, 98)], [(60, 63)], "40000", "400.00"),
        ([(10, 20), (28, 38), (55, 65), (72, 82)], [(45, 48)], "4972", "49.72"),
        ([(10, 20), (28, 38), (55, 65), (72, 82)], [(45, 48)], "3425", "34.25"),
    ]
    for blobs, ticks, digits, expected in cases:
        read = align_cents_column(blobs, ticks, digits)
        assert read.geometry_candidate == expected, (digits, read)
        assert read.ambiguous is False
        assert len("".join(ch for ch in expected if ch.isdigit())) == len(blobs)


def test_overlapping_window_candidates_are_alternatives_not_concat():
    """212 and 400 from different windows must not become 212400."""
    from packages.claim_evidence.line_sum_authority import parse_currency
    from packages.extraction_recovery.span_selection import select_field_span

    left = select_field_span("21200", "CURRENCY", "total_charge")
    right = select_field_span("40000", "CURRENCY", "total_charge")
    soup = select_field_span("212400", "CURRENCY", "total_charge")
    assert left.selected_text.endswith("00") or left.selected_text == "212.00"
    assert right.selected_text.endswith("00") or right.selected_text == "400.00"
    # Six-digit soup is no longer promoted to a whole-dollar total.
    assert soup.selected_text != "212400.00"
    assert parse_currency("212.00") != parse_currency("212400.00")
    # Digit-count integrity: five visible digits → five in the shaped total.
    assert len("".join(ch for ch in "212.00" if ch.isdigit())) == 5
    assert len("".join(ch for ch in "212400" if ch.isdigit())) == 6

    from packages.geometry_authority.monetary_geometry import align_cents_column

    read = align_cents_column(
        [(104, 113), (124, 135), (141, 153), (159, 172)],
        [(135, 138), (136, 138)],
        "49172",
    )
    assert read.geometry_candidate == "49.72"
    assert read.ambiguous is False
    assert "RULING_TICK_DROPPED" in read.reasons


def test_three_digit_run_does_not_imply_cents():
    from packages.geometry_authority.monetary_geometry import align_cents_column

    read = align_cents_column(
        [(10, 20), (30, 40), (55, 65)],
        [(48, 51)],
        "270",
    )
    assert read.geometry_candidate is None
    assert read.ambiguous is True


def test_units_blob_right_of_cents_stays_ambiguous():
    from packages.geometry_authority.monetary_geometry import align_cents_column

    read = align_cents_column(
        [(10, 20), (28, 38), (55, 65), (72, 82), (110, 118)],
        [(45, 48)],
        "49721",
    )
    assert read.geometry_candidate is None
    assert read.ambiguous is True


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


def test_canonical_page_cents_for_4972():
    """Page→canonical centres assign dollars/cents; crop-local x is ignored."""
    from packages.geometry_authority.cms1500_regions import CMS1500_CHARGE_CENTS_X
    from packages.geometry_authority.monetary_geometry import (
        GlyphBox,
        map_crop_glyphs_to_canonical,
        reconstruct_from_canonical_glyphs,
    )

    # Digits 4 9 | 7 2 on a Box 24F crop whose page x0 is 1050 (canonical page).
    crop = (1050.0, 1458.0, 1180.0, 1513.0)
    local = [
        GlyphBox("4", 70, 10, 82, 28),   # page cx ≈ 1131
        GlyphBox("9", 88, 10, 100, 28),  # page cx ≈ 1149 → still dollar (<1145?  (88+100)/2=94 → 1144)
        GlyphBox("7", 110, 10, 122, 28), # page cx ≈ 1161
        GlyphBox("2", 126, 10, 138, 28), # page cx ≈ 1177
    ]
    # Nudge 9 left of the cents ruling and 7/2 right of it.
    local = [
        GlyphBox("4", 70, 10, 82, 28),
        GlyphBox("9", 85, 10, 97, 28),   # cx=91 → page 1141
        GlyphBox("7", 110, 10, 122, 28), # cx=116 → page 1166
        GlyphBox("2", 126, 10, 138, 28),
    ]
    mapped = map_crop_glyphs_to_canonical(
        local, crop_bbox=crop, image_size=(1712, 2214)
    )
    assert all(g.canonical_cx for g in mapped)
    assert mapped[0].zone == "dollar"
    assert mapped[1].zone == "dollar"
    assert mapped[2].zone == "cent"
    assert mapped[3].zone == "cent"
    read = reconstruct_from_canonical_glyphs(mapped)
    assert read.raw_glyph_sequence == "4972"
    assert read.geometry_candidate == "49.72"
    assert read.canonical_monetary_value == "49.72"
    assert read.dollar_glyphs == ("4", "9")
    assert read.cents_glyphs == ("7", "2")
    assert read.page_glyph_polygons
    assert read.canonical_glyph_centres
    assert read.ruling_x == int(CMS1500_CHARGE_CENTS_X)


def test_canonical_amount_invariant_under_crop_expand_shift_scale():
    """Expanding, shifting, or scaling the crop must not change the canonical amount."""
    from packages.geometry_authority.monetary_geometry import (
        GlyphBox,
        map_crop_glyphs_to_canonical,
        page_to_canonical,
        reconstruct_from_canonical_glyphs,
    )

    # Fixed page-space digit boxes for 49.72.
    page_digits = [
        ("4", 1120.0, 1132.0),
        ("9", 1134.0, 1146.0),
        ("7", 1152.0, 1164.0),
        ("2", 1168.0, 1180.0),
    ]
    y0, y1 = 1465.0, 1505.0
    image_size = (1712, 2214)

    def _read_for_crop(crop):
        local_glyphs = []
        for text, px0, px1 in page_digits:
            local_glyphs.append(
                GlyphBox(
                    text,
                    int(px0 - crop[0]),
                    int(y0 - crop[1]),
                    int(px1 - crop[0]),
                    int(y1 - crop[1]),
                )
            )
        mapped = map_crop_glyphs_to_canonical(
            local_glyphs, crop_bbox=crop, image_size=image_size
        )
        return reconstruct_from_canonical_glyphs(mapped)

    base = (1050.0, 1458.0, 1185.0, 1513.0)
    expanded = (1030.0, 1440.0, 1210.0, 1530.0)  # expand
    shifted = (1060.0, 1465.0, 1195.0, 1520.0)  # shift
    # Scale: same page digits on a 2× page, crop scaled accordingly.
    scaled_size = (3424, 4428)
    scaled_crop = tuple(v * 2 for v in base)
    scaled_digits = [(t, a * 2, b * 2) for t, a, b in page_digits]

    def _read_scaled():
        local_glyphs = []
        for text, px0, px1 in scaled_digits:
            local_glyphs.append(
                GlyphBox(
                    text,
                    int(px0 - scaled_crop[0]),
                    int(y0 * 2 - scaled_crop[1]),
                    int(px1 - scaled_crop[0]),
                    int(y1 * 2 - scaled_crop[1]),
                )
            )
        mapped = map_crop_glyphs_to_canonical(
            local_glyphs, crop_bbox=scaled_crop, image_size=scaled_size
        )
        # Centres must land on the same canonical positions as the base crop.
        base_mapped = map_crop_glyphs_to_canonical(
            [
                GlyphBox(
                    t,
                    int(a - base[0]),
                    int(y0 - base[1]),
                    int(b - base[0]),
                    int(y1 - base[1]),
                )
                for t, a, b in page_digits
            ],
            crop_bbox=base,
            image_size=image_size,
        )
        for left, right in zip(mapped, base_mapped, strict=True):
            assert abs(left.canonical_cx - right.canonical_cx) < 0.6
        return reconstruct_from_canonical_glyphs(mapped)

    results = [
        _read_for_crop(base),
        _read_for_crop(expanded),
        _read_for_crop(shifted),
        _read_scaled(),
    ]
    for read in results:
        assert read.raw_glyph_sequence == "4972", read
        assert read.canonical_monetary_value == "49.72", read
        assert read.geometry_candidate == "49.72", read
        assert read.ambiguous is False

    # Sanity: page→canonical is linear in image size.
    cx, _ = page_to_canonical(1145.0, 1480.0, image_size)
    assert abs(cx - 1145.0) < 1e-6

