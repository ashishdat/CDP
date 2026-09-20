"""Precision-safe charge total authority — FA pattern regressions."""

from __future__ import annotations

from packages.claim_evidence.box28_line_sum_authority import (
    evaluate_box28_line_sum_authority,
)
from packages.claim_evidence.charge_total_authority import (
    is_ruling_tail_extension,
    is_units_bleed_cents,
    prefer_safe_charge_amount,
    resolve_safe_charge_total,
)
from packages.ocr_portfolio.monetary_recognizer import prefer_charge_ink_amount


def test_ruling_tail_70_vs_701():
    assert is_ruling_tail_extension("70.00", "701.00")
    # Untagged pair abstains — tagged resolve below selects the full stem.
    assert prefer_safe_charge_amount("70.00", "701.00") is None
    assert prefer_charge_ink_amount("70.00", "701.00") == "70.00"
    safe, reason = resolve_safe_charge_total(
        primary="701.00",
        field_payload={
            "ocr": {
                "candidates": [
                    {
                        "value": "70.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:full",
                    },
                    {
                        "value": "701.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:dollars_ruling",
                    },
                ]
            }
        },
        service_lines=[
            {
                "charges": "701.00",
                "candidates": [
                    {
                        "value": "701.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:dollars_ruling",
                    },
                    {
                        "value": "70.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:full",
                    },
                ],
            }
        ],
    )
    assert safe == "70.00"
    assert reason == "RULING_TAIL_TO_FULL_STEM"


def test_units_bleed_cents_prefer_whole_dollar():
    assert is_units_bleed_cents("157.07")
    assert is_units_bleed_cents("228.32")
    assert is_units_bleed_cents("25.43")
    assert not is_units_bleed_cents("157.00")
    assert not is_units_bleed_cents("49.72")
    assert prefer_safe_charge_amount("157.07", "157.00") == "157.00"
    safe, reason = resolve_safe_charge_total(
        primary="157.07",
        field_payload={
            "ocr": {
                "candidates": [
                    {"value": "157.07", "preprocessing_variant": "GEOMETRY_CENTS"},
                    {
                        "value": "157.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:dollars_ruling",
                    },
                ]
            }
        },
        service_lines=[{"charges": "157.07"}],
    )
    assert safe == "157.00"
    assert reason in {"SAFE_CHARGE_AUTHORITY", "BLEED_CENTS_TO_WHOLE_DOLLAR"}


def test_bleed_cents_without_glyph_proof_blocks_box28_line_sum_auto():
    decision = evaluate_box28_line_sum_authority(
        box28_amount="157.07",
        service_lines=[
            {
                "line_number": 1,
                "charges": "157.07",
                "raw_charges": "15707",
                "canonical_region": [1050, 1458, 1180, 1513],
                "candidates": [{"value": "157.07", "engine": "paddleocr"}],
            }
        ],
        box28_region=(1045.0, 1825.0, 1248.0, 1875.0),
        box28_observation={
            "text": "157.07",
            "raw_digit_sequence": "15707",
            "canonical_monetary_value": "157.07",
            "adopted": True,
        },
    )
    assert decision.disposition == "HUMAN_REVIEW_REQUIRED"
    assert decision.failed_predicate == "bleed_cents_require_glyph_proof"


def test_reject_place_shift_soup_still():
    from packages.claim_evidence.box28_line_sum_authority import evaluate_parser_integrity

    for bad in ("4972.00", "212400.00", "400406.00"):
        result = evaluate_parser_integrity(amount=bad, raw_digit_sequence=bad.replace(".", ""))
        assert result.passed is False


def test_focus_safe_totals_still_preferred():
    # .002 / .010 / .014 style clean amounts must not be rewritten.
    for amount in ("270.00", "49.72", "212.00", "400.00"):
        safe, _reason = resolve_safe_charge_total(
            primary=amount,
            field_payload={"ocr": {"candidates": [{"value": amount}]}},
            service_lines=[{"charges": amount, "candidates": [{"value": amount}]}],
        )
        assert safe == amount


def test_never_collapse_251_to_25():
    # Common-mode near-miss / digit-drop must abstain — never invent 25.00.
    safe, reason = resolve_safe_charge_total(
        primary="251.00",
        field_payload={
            "ocr": {
                "candidates": [
                    {
                        "value": "251.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:full",
                    },
                    {
                        "value": "25.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:dollars_ruling",
                    },
                ]
            }
        },
        service_lines=[{"charges": "251.00"}],
    )
    assert safe == "251.00"
    assert reason == "PRIMARY_UNCHANGED"
    assert prefer_safe_charge_amount("251.00", "25.00") is None
    # Shorter ruling crop must not rewrite a longer primary.
    safe2, reason2 = resolve_safe_charge_total(
        primary="251.00",
        field_payload={
            "ocr": {
                "candidates": [
                    {
                        "value": "25.00",
                        "preprocessing_variant": "charge_digit_whitelist_fast:dollars_ruling",
                    }
                ]
            }
        },
        service_lines=[{"charges": "251.00"}],
    )
    assert safe2 == "251.00"
    assert reason2 == "PRIMARY_UNCHANGED"


def test_ruling_tail_does_not_extend_short_stems():
    # Single-digit stems must not collapse via ruling-tail rules.
    assert not is_ruling_tail_extension("5.00", "51.00")
    assert prefer_safe_charge_amount("5.00", "51.00") is None
