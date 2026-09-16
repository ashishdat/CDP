from decimal import Decimal

from packages.claim_evidence.line_sum_authority import (
    is_suspicious_tiny_total,
    line_sum_total,
    should_defer_box28_to_line_sum,
)


def test_suspicious_tiny_matches_cascade_rule():
    assert is_suspicious_tiny_total(Decimal("2.22"))
    assert not is_suspicious_tiny_total(Decimal("22.00"))
    assert not is_suspicious_tiny_total(Decimal("1600.00"))


def test_defer_when_box28_empty_or_tiny():
    lines = [{"charges": "498.00"}, {"charges": "66.00"}]
    assert should_defer_box28_to_line_sum(None, lines)
    assert should_defer_box28_to_line_sum("2.22", lines)
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

