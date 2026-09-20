"""Box 28 ↔ Box 24F integrity corroboration regressions.

DJJM.002 / .010 / .014 must AUTO when both printed paths pass integrity,
agree, and use independent ROIs. False totals and duplicated glyphs stay HITL.
"""

from __future__ import annotations

from packages.claim_evidence.box28_line_sum_authority import (
    evaluate_box28_line_sum_authority,
    evaluate_parser_integrity,
    regions_are_independent,
)


def _box28_obs(
    amount: str,
    *,
    dollars: list[str],
    cents: list[str],
    centres: list[tuple[float, float]],
    raw: str | None = None,
    units: list[str] | None = None,
) -> dict:
    return {
        "text": raw or amount,
        "raw_digit_sequence": raw or amount.replace(".", ""),
        "canonical_monetary_value": amount,
        "dollar_glyphs": dollars,
        "cents_glyphs": cents,
        "unit_zone_glyphs": units or [],
        "canonical_glyph_centres": [list(c) for c in centres],
        "page_glyph_polygons": [
            [[c[0] - 4, c[1] - 4], [c[0] + 4, c[1] - 4], [c[0] + 4, c[1] + 4], [c[0] - 4, c[1] + 4]]
            for c in centres
        ],
        "adopted": True,
    }


def test_djjm_002_box28_line_sum_auto_270():
    """DJJM.002 → 270.00 AUTO_ACCEPTED via independent Box 28 ↔ Box 24F."""
    box28_region = (1045.0, 1825.0, 1248.0, 1875.0)
    line = {
        "line_number": 1,
        "charges": "270.00",
        "raw_charges": "27000",
        "canonical_region": [1050, 1458, 1165, 1513],
        "candidates": [
            {"value": "270.00", "engine": "paddleocr", "preprocessing_variant": "CURRENCY_DECIMAL_V2"},
            {"value": "270.00", "engine": "rapidocr", "preprocessing_variant": "CURRENCY_DECIMAL_V2"},
        ],
        "attempts": [
            {
                "reason": "GEOMETRY_CENTS",
                "observation": _box28_obs(
                    "270.00",
                    dollars=["2", "7", "0"],
                    cents=["0", "0"],
                    centres=[(1099.0, 1478.5), (1112.0, 1478.5), (1123.0, 1478.5), (1146.5, 1482.0), (1160.0, 1476.5)],
                    raw="27000",
                ),
            }
        ],
    }
    decision = evaluate_box28_line_sum_authority(
        box28_amount="270.00",
        service_lines=[line],
        box28_region=box28_region,
        box28_observation=_box28_obs(
            "270.00",
            dollars=["2", "7", "0"],
            cents=["0", "0"],
            centres=[(1090.0, 1850.0), (1105.0, 1850.0), (1120.0, 1850.0), (1160.0, 1850.0), (1175.0, 1850.0)],
            raw="27000",
        ),
    )
    assert decision.disposition == "AUTO_ACCEPTED"
    assert decision.amount == "270.00"
    assert decision.authority_reason == "BOX28_LINE_SUM_CORROBORATED"
    assert decision.failed_predicate is None
    assert {p.name: p.value for p in decision.predicates}["box28.parser_integrity"] is True
    assert {p.name: p.value for p in decision.predicates}["line_sum.parser_integrity"] is True
    assert {p.name: p.value for p in decision.predicates}["evidence_regions_are_independent"] is True


def test_djjm_010_requires_two_independent_integrity_paths():
    """DJJM.010 → 49.72 AUTO only when Box 28 and Box 24F both pass integrity."""
    box28_region = (1045.0, 1825.0, 1248.0, 1875.0)
    line = {
        "line_number": 1,
        "charges": "49.72",
        "raw_charges": "4972",
        "canonical_region": [1050, 1458, 1180, 1513],
        "candidates": [
            {"value": "49.72", "engine": "paddleocr"},
            {"value": "49.72", "engine": "rapidocr"},
        ],
        "attempts": [
            {
                "reason": "GEOMETRY_CENTS",
                "observation": _box28_obs(
                    "49.72",
                    dollars=["4", "9"],
                    cents=["7", "2"],
                    centres=[(1120.0, 1491.0), (1138.5, 1489.0), (1157.0, 1491.0), (1174.0, 1490.5)],
                    raw="4972",
                ),
            }
        ],
    }
    # Dual independent integrity-passing paths → AUTO.
    dual = evaluate_box28_line_sum_authority(
        box28_amount="49.72",
        service_lines=[line],
        box28_region=box28_region,
        box28_observation=_box28_obs(
            "49.72",
            dollars=["4", "9"],
            cents=["7", "2"],
            centres=[(1120.0, 1850.0), (1138.0, 1850.0), (1160.0, 1850.0), (1175.0, 1850.0)],
            raw="4972",
        ),
    )
    assert dual.disposition == "AUTO_ACCEPTED"
    assert dual.amount == "49.72"
    assert dual.authority_reason == "BOX28_LINE_SUM_CORROBORATED"

    # Line-only path (Box 28 integrity fails) → HITL.
    line_only = evaluate_box28_line_sum_authority(
        box28_amount="972.00",
        service_lines=[line],
        box28_region=box28_region,
        box28_observation={
            "text": "972",
            "raw_digit_sequence": "972",
            "canonical_monetary_value": "972.00",
            "dollar_glyphs": [],
            "cents_glyphs": [],
            "unit_zone_glyphs": [],
            "canonical_glyph_centres": [],
            "adopted": True,
        },
    )
    assert line_only.disposition == "HUMAN_REVIEW_REQUIRED"
    assert line_only.authority_reason in {
        "BOX28_INTEGRITY_FAILED",
        "AMOUNT_MISMATCH",
    }


def test_djjm_014_requires_observed_box28_212():
    """A line sum cannot pick a missing/contaminated Box 28 interpretation."""
    box28_region = (1045.0, 1825.0, 1248.0, 1875.0)
    line = {
        "line_number": 1,
        "charges": "212.00",
        "raw_charges": "21200",
        "canonical_region": [1050, 1458, 1165, 1513],
        "candidates": [
            {"value": "212.00", "engine": "paddleocr"},
            {"value": "212.00", "engine": "rapidocr"},
        ],
        "attempts": [
            {
                "reason": "GEOMETRY_CENTS",
                "observation": _box28_obs(
                    "212.00",
                    dollars=["2", "1", "2"],
                    cents=["0", "0"],
                    centres=[(1099.0, 1478.5), (1112.0, 1478.5), (1123.0, 1478.5), (1146.5, 1482.0), (1160.0, 1476.5)],
                    raw="21200",
                ),
            }
        ],
    }
    decision = evaluate_box28_line_sum_authority(
        box28_amount="5212.00",
        service_lines=[line],
        box28_region=box28_region,
        box28_field_payload={
            "candidates": [
                {"value": "5212.00", "raw_value": "521200", "engine": "paddleocr"},
            ]
        },
        box28_observation={
            "text": "120",
            "raw_digit_sequence": "120",
            "canonical_monetary_value": "1.20",
            "dollar_glyphs": ["1"],
            "cents_glyphs": ["2", "0"],
            "unit_zone_glyphs": [],
            "canonical_glyph_centres": [[1150.5, 1854.0], [1166.5, 1854.0], [1190.5, 1853.5]],
            "adopted": False,
        },
    )
    assert decision.disposition == "HUMAN_REVIEW_REQUIRED"
    assert decision.amount is None
    assert decision.authority_reason == "BOX28_INTEGRITY_FAILED"


def test_reject_false_totals_4972_212400_400406():
    # Digit-soup / impossible CMS totals fail integrity outright.
    for bad in ("4972.00", "212400.00", "400406.00"):
        result = evaluate_parser_integrity(amount=bad, raw_digit_sequence=bad.replace(".", ""))
        assert result.passed is False
        assert result.rejection_reason in {"IMPLAUSIBLE_TOTAL", "DIGIT_SOUP", "DECIMAL_GEOMETRY_REQUIRED"}

    # 4972.00 must never be the AUTO total; place-shift reinterprets to 49.72
    # only when an independent integrity-passing line sum corroborates.
    line = {
        "line_number": 1,
        "charges": "49.72",
        "raw_charges": "4972",
        "canonical_region": [1050, 1458, 1180, 1513],
        "candidates": [{"value": "49.72", "engine": "paddleocr"}],
        "attempts": [
            {
                "reason": "GEOMETRY_CENTS",
                "observation": _box28_obs(
                    "49.72",
                    dollars=["4", "9"],
                    cents=["7", "2"],
                    centres=[(1120.0, 1491.0), (1138.5, 1489.0), (1157.0, 1491.0), (1174.0, 1490.5)],
                    raw="4972",
                ),
            }
        ],
    }
    decision = evaluate_box28_line_sum_authority(
        box28_amount="4972.00",
        service_lines=[line],
        box28_region=(1045.0, 1825.0, 1248.0, 1875.0),
        box28_observation={
            "text": "4972",
            "raw_digit_sequence": "4972",
            "canonical_monetary_value": "4972.00",
            "adopted": True,
        },
    )
    assert decision.amount != "4972.00"
    if decision.disposition == "AUTO_ACCEPTED":
        assert decision.amount == "49.72"
        assert decision.authority_reason == "BOX28_LINE_SUM_CORROBORATED"


def test_reject_duplicated_and_unmapped_glyph_provenance():
    unmapped = evaluate_parser_integrity(
        amount="49.72",
        raw_digit_sequence="4972",
        dollar_glyphs=["4", "9"],
        cents_glyphs=["7", "2"],
        canonical_glyph_centres=[(1.0, 1.0), (2.0, 1.0)],  # fewer than digits
    )
    assert unmapped.passed is False
    assert unmapped.rejection_reason == "UNMAPPED_GLYPH_PROVENANCE"

    duplicated = evaluate_parser_integrity(
        amount="49.72",
        raw_digit_sequence="4972",
        dollar_glyphs=["4", "9"],
        cents_glyphs=["7", "2"],
        canonical_glyph_centres=[
            (1120.0, 1491.0),
            (1120.0, 1491.0),  # duplicate
            (1157.0, 1491.0),
            (1174.0, 1490.5),
        ],
    )
    assert duplicated.passed is False
    assert duplicated.rejection_reason == "DUPLICATED_GLYPH_PROVENANCE"


def test_overlapping_rois_are_not_independent():
    box28 = (1045.0, 1458.0, 1248.0, 1513.0)  # same band as line
    line = (1050.0, 1458.0, 1180.0, 1513.0)
    assert regions_are_independent(box28, [line]) is False


def test_cents_clipped_line_requires_review_even_when_candidate_agrees():
    """A clipped 24F crop cannot form an independent financial occurrence."""
    box28_region = (1045.0, 1825.0, 1248.0, 1875.0)
    line = {
        "line_number": 1,
        "charges": "27.01",
        "raw_charges": "2701",
        "canonical_region": [1000, 1458, 1145, 1513],  # cents-clipped
        "candidates": [
            {
                "value": "270.00",
                "engine": "paddleocr",
                "preprocessing_variant": "CURRENCY_DECIMAL_V2",
                "bounding_box": {"x0": 1000, "y0": 1458, "x1": 1145, "y1": 1513},
            },
            {
                "value": "270.00",
                "engine": "rapidocr",
                "preprocessing_variant": "CURRENCY_DECIMAL_V2",
                "bounding_box": {"x0": 1000, "y0": 1458, "x1": 1145, "y1": 1513},
            },
            {
                "value": "27.01",
                "engine": "rapidocr",
                "preprocessing_variant": "GEOMETRY_CENTS",
                "bounding_box": {"x0": 1000, "y0": 1458, "x1": 1145, "y1": 1513},
            },
        ],
        "attempts": [
            {
                "reason": "GEOMETRY_CENTS|BOX24F_CENTS_CLIPPED",
                "observation": _box28_obs(
                    "27.01",
                    dollars=["2", "7"],
                    cents=["0", "1"],
                    centres=[(1106.0, 1490.0), (1118.5, 1490.0), (1130.0, 1490.5), (1141.0, 1485.0)],
                    raw="2701",
                ),
            }
        ],
    }
    decision = evaluate_box28_line_sum_authority(
        box28_amount="270.00",
        service_lines=[line],
        box28_region=box28_region,
        box28_observation=_box28_obs(
            "270.00",
            dollars=["2", "7", "0"],
            cents=["0", "0"],
            centres=[(1090.0, 1850.0), (1105.0, 1850.0), (1120.0, 1850.0), (1160.0, 1850.0), (1175.0, 1850.0)],
            raw="27000",
        ),
    )
    assert decision.line_sum_amount == "270.00"
    assert decision.disposition == "HUMAN_REVIEW_REQUIRED"
    assert decision.amount is None
