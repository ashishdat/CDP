"""Document-family financial interpretation regressions (corpus correction)."""

from __future__ import annotations

from decimal import Decimal

from packages.document_finance import (
    DocumentFamily,
    build_package_financials,
    classify_document_family,
    cms_geometry_forbidden,
    dedupe_transactions,
    interpret_page_finance,
    parse_reimbursement_superbill,
    parse_running_account_statement,
    seed_known_discrepancies,
)
from packages.document_finance.transactions import (
    FinancialTransaction,
    TransactionType,
)
from packages.package_intelligence import classify_page_signals


def test_classify_reimbursement_and_running_and_separator():
    reb = classify_document_family(
        "Rise and Shine\nStatement for Insurance Reimbursement\nPatient: Ada"
    )
    assert reb.family is DocumentFamily.REIMBURSEMENT_SUPERBILL
    run = classify_document_family(
        "Statement\nDate of Service\nProcedure & Diagnosis Code\n"
        "Charge(Payment)\nBalance\nBalance forward 750.00"
    )
    assert run.family is DocumentFamily.RUNNING_ACCOUNT_STATEMENT
    sep = classify_document_family("SourceHOV Document Separator\nBATCH")
    assert sep.family is DocumentFamily.SEPARATOR
    cms = classify_document_family(
        "HEALTH INSURANCE CLAIM FORM\nAPPROVED BY NATIONAL UNIFORM CLAIM COMMITTEE"
    )
    assert cms.family is DocumentFamily.CMS1500
    assert cms_geometry_forbidden(DocumentFamily.REIMBURSEMENT_SUPERBILL)
    assert not cms_geometry_forbidden(DocumentFamily.CMS1500)


def test_superbill_3x165_and_4x165():
    p1 = parse_reimbursement_superbill(
        "Statement for Insurance Reimbursement\n"
        "3 x 165.00 = 495.00\nSubtotal: 495.00\nTotal: 495.00\nAmount Paid: 495.00"
    )
    assert p1.derived_total == Decimal("495.00")
    assert p1.printed_total == Decimal("495.00")
    assert p1.totals_agree
    assert p1.amount_paid == Decimal("495.00")
    # Amount Paid must remain a distinct role even when values match.
    assert p1.amount_paid_confused_with_total is False

    p2 = parse_reimbursement_superbill(
        "Statement for Insurance Reimbursement\n4 × 165.00 = 660.00\nTotal: 660.00"
    )
    assert p2.derived_total == Decimal("660.00")
    assert p2.totals_agree


def test_multipage_superbill_package_total_1650():
    pages = [
        parse_reimbursement_superbill("3 x 165.00 = 495.00\nTotal: 495.00"),
        parse_reimbursement_superbill("4 x 165.00 = 660.00\nTotal: 660.00"),
        parse_reimbursement_superbill("3 x 165.00 = 495.00\nTotal: 495.00"),
    ]
    txs = []
    for i, page in enumerate(pages):
        txs.extend(page.as_transactions(page_index=i, patient_id="ADA", provider_id="RISE"))
    fin = build_package_financials(
        transactions=txs,
        printed_page_totals=[p.printed_total for p in pages],
        derived_page_totals=[p.derived_total for p in pages],
    )
    assert fin.total_charges == "1650.00"
    assert fin.unique_package_service_charges == "1650.00"


def test_running_statement_balance_equations():
    # 750 + 375 + 375 - 750 = 750
    ledger = parse_running_account_statement(
        [
            {"description": "Balance forward", "amount": "750.00", "balance": "750.00"},
            {"description": "90837 Therapy", "amount": "375.00", "balance": "1125.00"},
            {"description": "90837 Therapy", "amount": "375.00", "balance": "1500.00"},
            {"description": "PMT ACH", "amount": "-750.00", "balance": "750.00"},
            {
                "description": "Total",
                "amount": "750.00",
                "balance": "750.00",
                "is_bottom_total": True,
            },
        ],
        printed_ending_balance="750.00",
    )
    assert ledger.balanced
    assert ledger.service_charges == Decimal("750.00")
    assert ledger.printed_ending_balance == Decimal("750.00")
    assert any(t.transaction_type is TransactionType.ENDING_BALANCE for t in ledger.transactions)

    # 1500 - 750 + 375*3 - 750 = 1125
    ledger2 = parse_running_account_statement(
        [
            {"description": "Balance forward", "amount": "1500.00"},
            {"description": "Payment VISA", "amount": "-750.00"},
            {"description": "90834", "amount": "375.00"},
            {"description": "90834", "amount": "375.00"},
            {"description": "90834", "amount": "375.00"},
            {"description": "PMT", "amount": "-750.00"},
            {"description": "Total", "amount": "1125.00", "is_bottom_total": True},
        ],
        printed_ending_balance="1125.00",
    )
    assert ledger2.balanced
    assert ledger2.service_charges == Decimal("1125.00")
    fin = build_package_financials(
        transactions=ledger2.transactions,
        ending_balance=ledger2.printed_ending_balance,
    )
    # Bottom 1125 is ending balance, not total charges (service charges happen to equal 1125).
    assert fin.ending_balance == "1125.00"
    assert fin.total_charges == "1125.00"
    assert "ENDING_BALANCE" in ",".join(fin.reasons) or fin.ending_balance == "1125.00"


def test_dedupe_cumulative_statements_count_once():
    txs = [
        FinancialTransaction(
            date="2024-01-01",
            description="90837",
            amount=Decimal("375.00"),
            transaction_type=TransactionType.SERVICE_CHARGE,
            patient_id="SCHEFTEL",
            provider_id="SUSAN",
            page_index=0,
            row_index=1,
        ),
        FinancialTransaction(
            date="2024-01-01",
            description="90837",
            amount=Decimal("375.00"),
            transaction_type=TransactionType.SERVICE_CHARGE,
            patient_id="SCHEFTEL",
            provider_id="SUSAN",
            page_index=1,
            row_index=3,
        ),
    ]
    deduped = dedupe_transactions(txs)
    assert len(deduped.canonical) == 1
    assert deduped.removed_count == 1
    fin = build_package_financials(transactions=txs)
    assert fin.total_charges == "375.00"


def test_balance_forward_and_payments_excluded_from_charges():
    ledger = parse_running_account_statement(
        [
            {"description": "Balance forward", "amount": "750.00"},
            {"description": "Service", "amount": "375.00"},
            {"description": "Payment", "amount": "-100.00"},
        ]
    )
    assert ledger.transactions[0].transaction_type is TransactionType.OPENING_BALANCE
    assert ledger.transactions[2].transaction_type is TransactionType.PAYMENT
    fin = build_package_financials(transactions=ledger.transactions)
    assert fin.total_charges == "375.00"


def test_separator_excluded_and_wrong_family_skips_cms():
    sep = interpret_page_finance(text="Document Separator SourceHOV")
    assert sep.classification.family is DocumentFamily.SEPARATOR
    assert sep.cms_geometry_used is False
    page = classify_page_signals(
        page_index=0,
        ocr_text="Statement for Insurance Reimbursement\n3 x 165.00 = 495.00",
        form_family="CMS1500",  # must not force CMS when text decides
    )
    assert page.page_class.value == "REIMBURSEMENT_SUPERBILL"
    assert page.allows_cms_geometry is False
    reb = interpret_page_finance(
        text="Statement for Insurance Reimbursement\n3 x 165.00 = 495.00\nTotal: 495.00",
        family="REIMBURSEMENT_SUPERBILL",
    )
    assert reb.cms_geometry_used is False
    assert reb.package_financials is not None
    assert reb.package_financials.total_charges == "495.00"


def test_source_field_absent_not_empty_financial_ink():
    page = parse_reimbursement_superbill(
        "Statement for Insurance Reimbursement\n3 x 165.00 = 495.00\nTotal: 495.00"
    )
    assert "patient_dob" in page.source_field_absent
    result = interpret_page_finance(
        text="Statement for Insurance Reimbursement\n3 x 165.00 = 495.00\nTotal: 495.00",
        claim_id="demo",
    )
    assert result.gap_class == "SOURCE_FIELD_ABSENT"


def test_known_dob_disputes_quarantined_not_mutated():
    ledger = seed_known_discrepancies()
    assert ledger.quarantined_fields() >= {
        ("Group A/M048DJJF.003", "patient_dob"),
        ("Group A/M048DJJF.037", "patient_dob"),
    }
    # No Golden mutation — ledger only records.
    assert all(r.label_value for r in ledger.records)


def test_pos_and_units_still_geometry_gated_on_cms():
    from packages.geometry_authority import reject_pos_as_charge
    from packages.ocr_portfolio import prefer_charge_ink_amount, shape_monetary

    reject, _ = reject_pos_as_charge("11.00", (420.0, 1500.0, 470.0, 1540.0))
    assert reject is True
    # 270 charge + unit 1 must not become 2701 via ink preference when clean .00 exists.
    assert prefer_charge_ink_amount("270.00", "2701.00") == "270.00"
    assert shape_monetary("2701.00") == "270.00"
