from decimal import Decimal

from packages.claim_evidence.line_sum_authority import (
    amounts_corroborate,
    is_implausible_charge_total,
    is_implausible_corroborator,
    is_suspicious_tiny_total,
    line_sum_auto_eligible,
    line_sum_total,
    should_defer_box28_to_line_sum,
)
from packages.extraction_recovery.field_cascade import semantic_accept


def test_suspicious_tiny_matches_cascade_rule():
    assert is_suspicious_tiny_total(Decimal("2.22"))
    assert not is_suspicious_tiny_total(Decimal("22.00"))
    assert not is_suspicious_tiny_total(Decimal("1600.00"))


def test_implausible_box28_digit_soup():
    assert is_implausible_charge_total("208408.00")
    assert is_implausible_charge_total("420840.00")
    assert not is_implausible_charge_total("2084.00")
    assert is_implausible_corroborator("208408.00", "200.00")
    assert is_implausible_corroborator("2084.00", "200.00")  # >5× line-sum
    assert is_implausible_corroborator("22.00", "400.00")  # <1/5 line-sum
    assert not is_implausible_corroborator("210.00", "200.00")
    assert not is_implausible_corroborator("222.00", "200.00")  # near-miss stays
    ok, reason = semantic_accept("total_charge", "208408.00")
    assert not ok and reason == "CURRENCY_IMPLAUSIBLE_TOTAL"


def test_defer_when_box28_empty_or_tiny():
    lines = [{"charges": "498.00"}, {"charges": "66.00"}]
    assert should_defer_box28_to_line_sum(None, lines)
    assert should_defer_box28_to_line_sum("2.22", lines)
    assert should_defer_box28_to_line_sum("208408.00", lines)
    assert line_sum_total(lines) == "564.00"


def test_defer_when_uncalibrated_ocr_contradicts_multi_line_sum():
    lines = [{"charges": "200.00"}, {"charges": "200.00"}, {"charges": "1200.00"}]
    assert should_defer_box28_to_line_sum("198240.00", lines)
    assert not should_defer_box28_to_line_sum("1600.00", lines)


def test_single_line_does_not_override_plausible_box28():
    lines = [{"charges": "305.00"}]
    assert not should_defer_box28_to_line_sum("305.00", lines)
    # Near-miss box-28 stays with OCR (diff 95 < 50% of 305).
    assert not should_defer_box28_to_line_sum("400.00", lines)
    assert should_defer_box28_to_line_sum("2.22", lines)


def test_single_line_defers_wild_box28_contradiction():
    """v11.5: box-28 22.00 vs single line 305.00 is not a plausible total."""
    lines = [{"charges": "305.00"}]
    assert should_defer_box28_to_line_sum("22.00", lines)
    assert line_sum_total(lines) == "305.00"


def test_amounts_corroborate_tolerance_and_digit_twin():
    assert amounts_corroborate("400.00", "400.00")
    assert amounts_corroborate("157.00", "1571.00")
    assert not amounts_corroborate("270.00", "424.00")
    assert not amounts_corroborate("600.00", "1600.00")


def test_line_sum_auto_requires_dual_engine_or_di():
    bare = [{"charges": "424.00", "candidates": [{"value": "424.00", "engine": "paddleocr"}]}]
    ok, reason = line_sum_auto_eligible(bare)
    assert not ok
    assert reason == "SINGLE_LINE_REQUIRES_DI"

    # Single-line paddle+rapid agree is still insufficient without DI / gpt-4o.
    single_dual = [
        {
            "charges": "222.00",
            "candidates": [
                {"value": "222.00", "engine": "paddleocr"},
                {"value": "222.00", "engine": "rapidocr"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(single_dual)
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"

    # paddle+rapid+gpt-4o consensus unlocks single-line AUTO (DI quota hole).
    single_triple = [
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
                {"value": "200.00", "engine": "azure_gpt4o_crop"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(single_triple)
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    # gpt-4o + paddle alone (rapid empty) is enough — common on this slice.
    single_gpt_paddle = [
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "azure_gpt4o_crop"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(single_gpt_paddle)
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    # gpt-4o vs disagreeing local → still HITL.
    conflict_local = [
        {
            "charges": "200.00",
            "candidates": [
                {"value": "900.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "azure_gpt4o_crop"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(conflict_local)
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"

    # Junk box-28 must not force CONFLICT over a gpt-4o-local line.
    ok, reason = line_sum_auto_eligible(
        single_triple, corroborating_values=["208408.00"]
    )
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    dual = [
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
            ],
        },
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(dual)
    assert ok and reason == "DUAL_ENGINE_LINE_AGREEMENT"

    # paddle + gpt-4o residual agreeing is NOT independent dual-engine AUTO.
    paddle_gpt4o = [
        {
            "charges": "485.00",
            "candidates": [
                {"value": "485.00", "engine": "paddleocr"},
                {"value": "485.00", "engine": "azure_gpt4o_crop"},
            ],
        },
        {
            "charges": "485.00",
            "candidates": [
                {"value": "485.00", "engine": "paddleocr"},
                {"value": "485.00", "engine": "azure_gpt4o_crop"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(paddle_gpt4o)
    assert not ok and reason == "MULTI_LINE_UNCORROBORATED"

    ok, reason = line_sum_auto_eligible(bare, corroborating_values=["424.00"])
    assert ok and reason == "BOX28_OR_DI_CORROBORATED"

    ok, reason = line_sum_auto_eligible(bare, corroborating_values=["270.00"])
    assert not ok and reason == "BOX28_OR_DI_CONFLICT"

    # Digit-drop twin across engines is not dual-engine agreement for AUTO.
    twin_line = [
        {
            "charges": "131.00",
            "candidates": [
                {"value": "13.00", "engine": "paddleocr"},
                {"value": "131.00", "engine": "rapidocr"},
            ],
        },
        {
            "charges": "4.00",
            "candidates": [
                {"value": "4.00", "engine": "paddleocr"},
                {"value": "4.00", "engine": "rapidocr"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(twin_line)
    assert not ok and reason == "MULTI_LINE_UNCORROBORATED"
