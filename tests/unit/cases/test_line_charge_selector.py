"""LineChargeSelector — charge-column selection without Box 28 / line-sum."""

from packages.claim_evidence.line_charge_selector import (
    apply_line_charge_selector,
    select_line_charge,
)
from packages.claim_evidence.financial_geometry_authority import (
    evaluate_financial_geometry_arithmetic,
)


def _cand(engine, value, raw=None, bbox=None):
    payload = {
        "engine": engine,
        "value": value,
        "raw_value": raw if raw is not None else value,
    }
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        payload["bounding_box"] = {
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "image_width": 1712,
            "image_height": 2214,
        }
    return payload


# Charge-column band inside Box 24F (reference px).
_CHARGE_BBOX = (1050.0, 1458.0, 1180.0, 1513.0)
_UNITS_BBOX = (1210.0, 1458.0, 1280.0, 1513.0)
_POS_BBOX = (420.0, 1458.0, 470.0, 1513.0)


def test_selects_dual_local_stem_over_units_concat():
    """6401 bleed loses to dual-local 640.00 in the charge column."""
    line = {
        "charges": "6401.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "640.00", "640", _CHARGE_BBOX),
            _cand("rapidocr", "640.00", "640", _CHARGE_BBOX),
            _cand("paddleocr", "6401.00", "6401", _CHARGE_BBOX),
            _cand("rapidocr", "640.40", "64040", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "640.00"


def test_rejects_pos_shell_and_selects_real_charge():
    """Selected 1.00 junk loses to dual-local 270.00."""
    line = {
        "charges": "1.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "1.00", "1", _POS_BBOX),
            _cand("paddleocr", "270.00", "270", _CHARGE_BBOX),
            _cand("rapidocr", "270.00", "270", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "270.00"


def test_rejects_units_column_overlap():
    line = {
        "charges": "2.00",
        "candidates": [
            _cand("paddleocr", "2.00", "2", _UNITS_BBOX),
            _cand("rapidocr", "2.00", "2", _UNITS_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "UNREADABLE_LINE_CHARGE"


def test_place_shift_4972_rejected_when_49_72_present():
    line = {
        "charges": "4972.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
            _cand("rapidocr", "49.72", "49.72", _CHARGE_BBOX),
            _cand("paddleocr", "49.72", "49.72", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "49.72"


def test_bare_digit_soup_alone_is_ambiguous_not_selected():
    """4972 with no observed-decimal peer stays conflict/HITL, not SELECTED."""
    line = {
        "charges": "4972.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "4972.00", "4972.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "AMBIGUOUS_LINE_CHARGE"
    assert result.reason in {
        "ONLY_BLEED_OR_SOUP_CANDIDATES",
        "NO_DUAL_LOCAL_AGREEMENT",
    }


def test_cents_first_raw_00_212_selects_dual_local():
    """OCR ``00\\n212`` must not collapse to SELECTION_NOISE 0.00."""
    line = {
        "charges": "212.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "212.00", "00\n212", _CHARGE_BBOX),
            _cand("rapidocr", "212.00", "00\n212", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "212.00", "212.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "212.00"
    assert result.reason == "DUAL_LOCAL_CHARGE_COLUMN"


def test_dollars_ruling_bbox_near_cents_line_is_in_column():
    """Dollars-ruling crop ending at x1≈1161 must still count as charge-column."""
    dollars_bbox = (1050.0, 1458.0, 1161.0, 1513.0)
    line = {
        "charges": "212.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "212.00", "212", dollars_bbox),
            _cand("rapidocr", "212.00", "212", dollars_bbox),
            _cand("azure_gpt4o_crop", "212.00", "212.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "212.00"


def test_geometry_cents_attempt_promoted_over_bare_soup():
    """GEOMETRY_CENTS on attempts unlocks selection when candidates are soup."""
    line = {
        "charges": "4972.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "4972.00", "4972.00", _CHARGE_BBOX),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "49.72",
                    "raw_digit_sequence": "4972",
                    "canonical_monetary_value": "49.72",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "49.72"


def test_dollars_ruling_truncation_does_not_beat_geometry():
    """Dual-local ``129.00`` must not erase GEOMETRY_CENTS ``1291.15``."""
    dollars_bbox = (1050.0, 1458.0, 1160.0, 1513.0)
    line = {
        "charges": "1291.15",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("azure_gpt4o_crop", "129.15", "129.15", _CHARGE_BBOX),
            _cand("paddleocr", "12919.00", "12919", _CHARGE_BBOX),
            _cand("paddleocr", "129.00", "129\n1", dollars_bbox),
            _cand("rapidocr", "129.00", "11\n129", dollars_bbox),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "1291.15",
                    "raw_digit_sequence": "129115",
                    "canonical_monetary_value": "1291.15",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "AMBIGUOUS_LINE_CHARGE"
    assert result.reason == "DOLLARS_TRUNCATION_VS_FULLER_READ"


def test_vision_fuller_cents_selected_when_locals_are_dollars_truncation():
    """Claude/gpt-4o ``157.07`` wins over dual-local dollars-ruling ``157.00``."""
    dollars_bbox = (1050.0, 1458.0, 1165.0, 1513.0)
    line = {
        "charges": "1571.07",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("paddleocr", "15707.00", "15707", _CHARGE_BBOX),
            _cand("paddleocr", "157.00", "157", dollars_bbox),
            _cand("rapidocr", "157.00", "157", dollars_bbox),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "157.07"
    assert result.reason == "VISION_FULLER_DOLLARS_STEM_CORROBORATED"


def test_dual_vision_overrides_geometry_cents_place_shift_soup():
    """gpt-4o+Claude 157.07 beat GEOMETRY_CENTS 1571.07 when locals stem-agree."""
    dollars_bbox = (1050.0, 1458.0, 1165.0, 1513.0)
    line = {
        "charges": "1571.07",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("paddleocr", "157.00", "157", dollars_bbox),
            _cand("rapidocr", "157.00", "157", dollars_bbox),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "1571.07",
                    "canonical_monetary_value": "1571.07",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "157.07"
    assert result.reason == "DUAL_VISION_FULLER_DOLLARS_STEM_CORROBORATED"


def test_units_prefix_raw_keeps_trailing_dollars_stem():
    """``70\\\\n157`` is units bleed then dollars, not dual-local 70.00."""
    from packages.claim_evidence.line_charge_selector import _shaped_amount

    shaped = _shaped_amount(_cand("paddleocr", "157.00", "70\n157", _CHARGE_BBOX))
    assert shaped == "157.00"
    shaped7 = _shaped_amount(_cand("paddleocr", "157.00", "7c\n157", _CHARGE_BBOX))
    assert shaped7 == "157.00"


def test_dual_vision_selects_when_locals_only_have_units_bleed():
    """DJKH.008-class: Claude+gpt4o 157.07 wins with no dual-local 157.00."""
    line = {
        "charges": "1571.07",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "157.07", "157.07", _CHARGE_BBOX),
            # Upstream value is 157.00 but raw was units-prefix bleed.
            _cand("paddleocr", "157.00", "70\n157", _CHARGE_BBOX),
            _cand("rapidocr", "15710.00", "15710:", _CHARGE_BBOX),
            _cand("rapidocr", "1571.00", "1571c", _CHARGE_BBOX),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "1571.07",
                    "canonical_monetary_value": "1571.07",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "157.07"
    assert result.reason in {
        "DUAL_VISION_AGREEMENT_WITHOUT_DUAL_LOCAL",
        "DUAL_VISION_FULLER_DOLLARS_STEM_CORROBORATED",
        "VISION_FULLER_DOLLARS_STEM_CORROBORATED",
    }


def test_ruling_split_raw_reconstructs_cents():
    """Local ``34\\n25`` is dollars|cents ink, not a dual-local 25.00."""
    line = {
        "charges": "25.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "25.00", "34\n25", _CHARGE_BBOX),
            _cand("rapidocr", "25.00", "34\n25", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "34.25", "34.25", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "34.25"


def test_units_bleed_tail_keeps_leading_dollars():
    """``212\\n100`` is dollars 212 with units bleed, not dual-local 100.00."""
    line = {
        "charges": "100.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "100.00", "212 i00", _CHARGE_BBOX),
            _cand("rapidocr", "100.00", "212\n100", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "212.00", "212.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "212.00"


def test_ambiguous_without_dual_local():
    line = {
        "charges": "200.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [_cand("paddleocr", "200.00", "200", _CHARGE_BBOX)],
    }
    result = select_line_charge(line)
    assert result.disposition == "AMBIGUOUS_LINE_CHARGE"


def test_apply_rewrites_service_line_charges():
    lines = [
        {
            "line_number": 1,
            "charges": "6401.00",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "640.00", "640", _CHARGE_BBOX),
                _cand("rapidocr", "640.00", "640", _CHARGE_BBOX),
                _cand("paddleocr", "6401.00", "6401", _CHARGE_BBOX),
            ],
        },
        {
            "line_number": 2,
            "charges": "2601.00",
            "canonical_region": [1050.0, 1513.0, 1180.0, 1568.0],
            "candidates": [
                _cand("paddleocr", "260.00", "260", (1050.0, 1513.0, 1180.0, 1568.0)),
                _cand("rapidocr", "260.00", "260", (1050.0, 1513.0, 1180.0, 1568.0)),
                _cand("paddleocr", "2601.00", "2601", (1050.0, 1513.0, 1180.0, 1568.0)),
            ],
        },
    ]
    out = apply_line_charge_selector(lines)
    assert out[0]["charges"] == "640.00"
    assert out[1]["charges"] == "260.00"
    assert out[0]["line_charge_selection"]["disposition"] == "SELECTED_LOCAL_CHARGE"


def test_financial_geometry_confirms_exact_arithmetic():
    lines = [
        {
            "charges": "115.00",
            "canonical_region": list(_CHARGE_BBOX),
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "115.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "115.00", "115.00", _CHARGE_BBOX),
                _cand("rapidocr", "115.00", "115.00", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="115.00",
        service_lines=lines,
        box28_observation={
            "text": "115.00",
            "raw_digit_sequence": "11500",
            "canonical_monetary_value": "115.00",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "115.00"
    assert decision.reason == "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED"


def test_financial_geometry_ignores_same_stem_box28_twin():
    """1160.40 beside confirmed 1160.00 is OCR twin noise, not a true conflict."""
    lines = [
        {
            "charges": "640.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "640.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "640.00", "640", _CHARGE_BBOX),
                _cand("rapidocr", "640.00", "640", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "260.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "260.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "260.00", "260", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "260.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "260.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "260.00", "260", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260", _CHARGE_BBOX),
            ],
        },
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="1160.00",
        service_lines=lines,
        box28_field_payload={
            "ranked_candidate": {
                "ocr_candidate": {"value": "1160.00", "raw_value": "1160.00"}
            },
            "alternatives": [
                {"ocr_candidate": {"value": "1160.40", "raw_value": "1160.40"}},
            ],
        },
        box28_observation={
            "text": "1160.00",
            "raw_digit_sequence": "116000",
            "canonical_monetary_value": "1160.00",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "1160.00"


def test_financial_geometry_keeps_true_conflict_as_hitl():
    lines = [
        {
            "charges": "260.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "260.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "260.00", "260", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="2605.00",
        service_lines=lines,
        box28_observation={"text": "2605.00", "raw_digit_sequence": "260500"},
    )
    assert not decision.confirmed
    assert decision.reason == "ARITHMETIC_MISMATCH"


def test_ambiguous_without_amount_clears_unsupported_stale_charges():
    """M.008: geometry 49.77 must not stick when selector amount is null."""
    lines = [
        {
            "line_number": 1,
            "charges": "49.77",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
                _cand("azure_gpt4o_crop", "4972.00", "4972.00", _CHARGE_BBOX),
            ],
            "attempts": [
                {
                    "engine": "rapidocr",
                    "reason": "GEOMETRY_CENTS",
                    "observation": {
                        "shaped": "49.77",
                        "raw_digit_sequence": "4977",
                        "canonical_monetary_value": "49.77",
                    },
                }
            ],
        }
    ]
    out = apply_line_charge_selector(lines)
    assert out[0]["line_charge_selection"]["disposition"] == "AMBIGUOUS_LINE_CHARGE"
    assert out[0]["line_charge_selection"]["amount"] is None
    assert out[0]["charges"] is None
    assert out[0]["charge_amount"] is None


def test_ambiguous_keeps_charge_when_gpt4o_candidate_supports_it():
    lines = [
        {
            "line_number": 1,
            "charges": "222.22",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("azure_gpt4o_crop", "222.22", "222.22", _CHARGE_BBOX),
                _cand("paddleocr", "222.00", "222", _CHARGE_BBOX),
                _cand("rapidocr", "22.00", "22", _CHARGE_BBOX),
            ],
        }
    ]
    out = apply_line_charge_selector(lines)
    assert out[0]["line_charge_selection"]["disposition"] == "AMBIGUOUS_LINE_CHARGE"
    assert out[0]["charges"] == "222.22"
