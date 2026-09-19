"""Running account statement (ledger) parser and balance reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .transactions import (
    FinancialTransaction,
    TransactionType,
    classify_ledger_row,
    format_money,
    parse_money,
)


@dataclass
class LedgerReconcileResult:
    opening_balance: Decimal | None = None
    ending_balance: Decimal | None = None
    printed_ending_balance: Decimal | None = None
    expected_ending_balance: Decimal | None = None
    service_charges: Decimal = Decimal("0.00")
    payments: Decimal = Decimal("0.00")
    adjustments: Decimal = Decimal("0.00")
    balanced: bool = False
    reasons: list[str] = field(default_factory=list)
    transactions: list[FinancialTransaction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "opening_balance": (
                format_money(self.opening_balance)
                if self.opening_balance is not None
                else None
            ),
            "ending_balance": (
                format_money(self.ending_balance)
                if self.ending_balance is not None
                else None
            ),
            "printed_ending_balance": (
                format_money(self.printed_ending_balance)
                if self.printed_ending_balance is not None
                else None
            ),
            "expected_ending_balance": (
                format_money(self.expected_ending_balance)
                if self.expected_ending_balance is not None
                else None
            ),
            "service_charges": format_money(self.service_charges),
            "payments": format_money(self.payments),
            "adjustments": format_money(self.adjustments),
            "balanced": self.balanced,
            "reasons": list(self.reasons),
            "transactions": [t.to_dict() for t in self.transactions],
            # Bottom total is ending balance — never total_charges.
            "total_charges_from_ledger": format_money(self.service_charges),
        }


def parse_running_account_statement(
    rows: list[dict[str, Any]],
    *,
    page_index: int = 0,
    patient_id: str | None = None,
    provider_id: str | None = None,
    printed_ending_balance: object = None,
) -> LedgerReconcileResult:
    """Parse ledger rows. Bottom Total → ENDING_BALANCE, not total charge.

    Each row dict may include: date, description, amount, balance, is_bottom_total.
    Amounts may be signed strings (negative / CR / parentheses = payment).
    """
    result = LedgerReconcileResult()
    printed = parse_money(printed_ending_balance)
    if printed is not None:
        result.printed_ending_balance = printed

    txs: list[FinancialTransaction] = []
    for idx, raw in enumerate(rows or []):
        amount = parse_money(raw.get("amount") or raw.get("charge_payment"))
        balance = parse_money(raw.get("balance"))
        desc = raw.get("description") or raw.get("procedure")
        is_bottom = bool(raw.get("is_bottom_total"))
        # Explicit bottom label on last money row.
        if not is_bottom and idx == len(rows) - 1:
            label = str(raw.get("label") or desc or "").upper()
            if "TOTAL" in label and "CHARGE" not in label:
                is_bottom = True
        tx_type = classify_ledger_row(
            description=str(desc or ""),
            amount=amount,
            is_bottom_total=is_bottom,
        )
        if raw.get("transaction_type"):
            try:
                tx_type = TransactionType(str(raw.get("transaction_type")))
            except ValueError:
                pass
        tx = FinancialTransaction(
            date=raw.get("date") or raw.get("service_date"),
            description=str(desc) if desc is not None else None,
            procedure_code=raw.get("procedure_code"),
            amount=amount,
            balance=balance,
            transaction_type=tx_type,
            provider_id=provider_id,
            patient_id=patient_id,
            page_index=page_index,
            row_index=idx,
            raw=dict(raw),
        )
        txs.append(tx)

    result.transactions = txs
    opening = Decimal("0.00")
    services = Decimal("0.00")
    payments = Decimal("0.00")
    adjustments = Decimal("0.00")
    ending: Decimal | None = None

    for tx in txs:
        if tx.transaction_type is TransactionType.OPENING_BALANCE:
            if tx.amount is not None:
                opening = tx.amount
            elif tx.balance is not None:
                opening = tx.balance
            result.opening_balance = opening
        elif tx.transaction_type is TransactionType.SERVICE_CHARGE and tx.amount is not None:
            services += tx.amount
        elif tx.transaction_type is TransactionType.PAYMENT and tx.amount is not None:
            payments += tx.amount  # already signed negative
        elif tx.transaction_type is TransactionType.ADJUSTMENT and tx.amount is not None:
            adjustments += tx.amount
        elif tx.transaction_type is TransactionType.ENDING_BALANCE:
            ending = tx.amount if tx.amount is not None else tx.balance
            if ending is not None:
                result.ending_balance = ending
                result.printed_ending_balance = result.printed_ending_balance or ending

    result.service_charges = services.quantize(Decimal("0.01"))
    result.payments = payments.quantize(Decimal("0.01"))
    result.adjustments = adjustments.quantize(Decimal("0.01"))
    if result.opening_balance is None and txs:
        # First balance-forward may only populate balance column.
        for tx in txs:
            if tx.transaction_type is TransactionType.OPENING_BALANCE:
                result.opening_balance = tx.balance or tx.amount or Decimal("0.00")
                break
        if result.opening_balance is None:
            result.opening_balance = Decimal("0.00")

    expected = (
        (result.opening_balance or Decimal("0.00"))
        + result.service_charges
        + result.payments
        + result.adjustments
    ).quantize(Decimal("0.01"))
    result.expected_ending_balance = expected
    target = result.printed_ending_balance or result.ending_balance
    if target is not None and abs(expected - target) <= Decimal("0.01"):
        result.balanced = True
        result.reasons.append("LEDGER_EQUATION_BALANCED")
    elif target is not None:
        result.reasons.append("LEDGER_EQUATION_MISMATCH")
    else:
        result.reasons.append("NO_PRINTED_ENDING_BALANCE")

    result.reasons.append("ENDING_BALANCE_NOT_TOTAL_CHARGE")
    return result
