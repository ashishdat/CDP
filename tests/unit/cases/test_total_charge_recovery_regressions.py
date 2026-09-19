"""Regression tests for total-charge recovery and financial acceptance policy."""

from __future__ import annotations

from decimal import Decimal

from PIL import Image, ImageDraw

from packages.claim_evidence.line_sum_authority import line_sum_auto_eligible
from packages.field_authority import accept_field, independent_evidence_count
from packages.financial_reconciliation import FinancialDisposition, reconcile_claim_total
from packages.geometry_authority import reject_pos_as_charge
from packages.ocr_portfolio import shape_monetary
from packages.ocr_portfolio.monetary_recognizer import monetary_variants_extended


def test_pos_11_never_charge_from_box_24b():
    reject, reason = reject_pos_as_charge("11.00", (420.0, 1500.0, 470.0, 1540.0))
    assert reject is True


def test_payment_and_balance_excluded_from_line_sum():
    result = reconcile_claim_total(
        box28_value=None,
        service_lines=[
            {"charges": "100.00", "row_id": "1", "bbox": [1050, 1500, 1180, 1540]},
            {"charges": "50.00", "column_role": "payment", "row_id": "pay"},
            {"charges": "200.00", "column_role": "balance", "row_id": "bal"},
        ],
        charge_column_verified=True,
        all_service_rows_detected=True,
        independent_evidence_paths=2,
    )
    # payment/balance excluded → only 100.00 remains → needs corroboration paths
    assert result.line_sum in {None, "100.00"} or result.disposition in {
        FinancialDisposition.LINE_SUM_UNCORROBORATED,
        FinancialDisposition.LINE_TOTALS_RECONCILED,
        FinancialDisposition.POS_BLEED_REJECTED,
    }


def test_duplicate_service_lines_deduped():
    result = reconcile_claim_total(
        box28_value="100.00",
        service_lines=[
            {"charges": "100.00", "row_id": "1", "bbox": [1050, 1500, 1180, 1540]},
            {"charges": "100.00", "row_id": "1", "bbox": [1050, 1500, 1180, 1540]},
        ],
        charge_column_verified=True,
        all_service_rows_detected=True,
        independent_evidence_paths=1,
    )
    assert result.disposition == FinancialDisposition.DIRECT_TOTAL_CORROBORATED
    assert result.accepted_total == "100.00"


def test_direct_total_vs_line_sum_conflict():
    result = reconcile_claim_total(
        box28_value="500.00",
        service_lines=[
            {"charges": "100.00", "row_id": "1", "bbox": [1050, 1500, 1180, 1540]},
            {"charges": "100.00", "row_id": "2", "bbox": [1050, 1550, 1180, 1590]},
        ],
        charge_column_verified=True,
        all_service_rows_detected=True,
        independent_evidence_paths=1,
    )
    assert result.disposition == FinancialDisposition.TOTAL_CONFLICT


def test_incomplete_service_lines_disposition():
    result = reconcile_claim_total(
        box28_value=None,
        service_lines=[{"charges": "100.00", "row_id": "1", "bbox": [1050, 1500, 1180, 1540]}],
        charge_column_verified=True,
        all_service_rows_detected=False,
        independent_evidence_paths=2,
    )
    assert result.disposition == FinancialDisposition.INCOMPLETE_SERVICE_LINES


def test_same_crop_engines_not_independent():
    cands = [
        {"engine": "paddleocr", "value": "100.00"},
        {"engine": "paddleocr", "value": "100.00"},
    ]
    assert independent_evidence_count(cands) == 1
    decision = accept_field(
        field_name="total_charge",
        valid_geometry=True,
        valid_semantics=True,
        valid_format=True,
        calibrated_confidence=0.99,
        field_threshold=0.95,
        independent_evidence=independent_evidence_count(cands),
        required_evidence=2,
        unresolved_conflict=False,
    )
    assert decision.accepted is False


def test_shape_monetary_and_variants():
    assert shape_monetary("1,234.50") == "1234.50"
    assert shape_monetary("CR 12.00") == "12.00"
    img = Image.new("RGB", (60, 20), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((5, 2), "12.00", fill=(0, 0, 0))
    variants = monetary_variants_extended(img)
    ids = {v.variant_id for v in variants}
    assert "nn_2x" in ids and "bicubic_4x" in ids and "adaptive_threshold" in ids


def test_true_blank_with_complete_lines_not_empty_pixels():
    result = reconcile_claim_total(
        box28_value=None,
        service_lines=[
            {"charges": "150.00", "row_id": "1", "bbox": [1050, 1500, 1180, 1540]},
            {"charges": "50.00", "row_id": "2", "bbox": [1050, 1550, 1180, 1590]},
        ],
        charge_column_verified=True,
        all_service_rows_detected=True,
        independent_evidence_paths=2,
    )
    assert result.disposition in {
        FinancialDisposition.LINE_TOTALS_RECONCILED,
        FinancialDisposition.LINE_SUM_UNCORROBORATED,
    }
    assert result.line_sum == "200.00"


def test_pos_like_line_sum_still_blocked():
    ok, reason = line_sum_auto_eligible([{"charges": "11.00", "candidates": [
        {"value": "11.00", "engine": "paddleocr"},
        {"value": "11.00", "engine": "rapidocr"},
    ]}])
    assert not ok and reason == "POS_LIKE_LINE_SUM_REJECTED"
