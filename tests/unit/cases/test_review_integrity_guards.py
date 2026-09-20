"""Adversarial review cases: agreement must not manufacture source evidence."""
from decimal import Decimal

import pytest

from packages.claim_evidence.box28_line_sum_authority import (
    build_box24f_rows,
    evaluate_box28_line_sum_authority,
    evaluate_parser_integrity,
    regions_are_independent,
)
from packages.claim_evidence.charge_total_authority import (
    prefer_safe_charge_amount,
    resolve_safe_charge_total,
)
from packages.claim_evidence.line_sum_authority import amounts_corroborate, parse_currency


@pytest.mark.parametrize('left,right', [('13.00', '131.00'), ('400.00', '400.40'), ('200.00', '209.00')])
def test_unequal_money_is_not_corroboration(left, right):
    assert not amounts_corroborate(left, right)


def test_service_sum_cannot_rewrite_box28():
    value, _ = resolve_safe_charge_total(
        primary='400.40', service_lines=[{'charges': '200.00'}, {'charges': '200.00'}]
    )
    assert value == '400.40'


@pytest.mark.parametrize('cents', ['40', '72', '01'])
def test_whole_dollars_are_not_automatically_preferred(cents):
    assert prefer_safe_charge_amount('400.00', f'400.{cents}') is None


def test_no_raw_evidence_cannot_pass_integrity():
    assert not evaluate_parser_integrity(amount='212.00').passed


def test_units_glyphs_cannot_fall_back_to_token_acceptance():
    assert not evaluate_parser_integrity(
        amount='212.00', raw_digit_sequence='21200', unit_zone_glyphs=['1']
    ).passed


def test_units_zone_allows_observed_decimal_token():
    """DJJM.002-class: units bleed + bad glyph split, but ``1 270.00`` is printed."""
    result = evaluate_parser_integrity(
        amount='270.00',
        raw_digit_sequence='1 270.00',
        dollar_glyphs=[],
        cents_glyphs=['2', '7', '0', '0'],
        unit_zone_glyphs=['0'],
    )
    assert result.passed
    assert result.amount == '270.00'
    assert 'OBSERVED_DECIMAL_TOKEN' in result.reasons


def test_observed_decimal_token_without_units():
    result = evaluate_parser_integrity(
        amount='270.00', raw_digit_sequence='$270.00'
    )
    assert result.passed
    assert 'OBSERVED_DECIMAL_TOKEN' in result.reasons


def test_ruling_digit_cannot_be_deleted_without_geometry():
    assert not evaluate_parser_integrity(amount='212.00', raw_digit_sequence='211200').passed


def test_missing_centres_cannot_pass_glyph_integrity():
    assert not evaluate_parser_integrity(
        amount='49.72', raw_digit_sequence='4972', dollar_glyphs=['4', '9'], cents_glyphs=['7', '2']
    ).passed


def test_normalized_shells_do_not_make_independent_evidence():
    decision = evaluate_box28_line_sum_authority(
        box28_amount='212.00', service_lines=[{'charges': '212.00'}]
    )
    assert decision.disposition == 'HUMAN_REVIEW_REQUIRED'


def test_unreadable_active_row_is_not_silently_omitted():
    rows = build_box24f_rows([{'charges': '212.00'}, {'procedure_code': '90834', 'charges': None}])
    assert len(rows) == 2
    assert not rows[1].integrity.passed


def test_zero_area_region_is_not_independent():
    assert not regions_are_independent((1045, 1825, 1248, 1875), [(1050, 1458, 1050, 1513)])


@pytest.mark.parametrize('raw', ['USD abc 212.00 xyz', '200.00 units 2', '60g.00', '1.234'])
def test_currency_parser_does_not_strip_arbitrary_text_or_round(raw):
    assert parse_currency(raw) is None


def test_currency_zero_and_valid_formats():
    assert parse_currency(0) == Decimal(0)
    assert parse_currency('$1,234.56') == Decimal('1234.56')
    assert parse_currency('49 72') == Decimal('49.72')
