"""Package-level financial semantics — separate roles, never collapsed early."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .transactions import (
    FinancialTransaction,
    TransactionType,
    dedupe_transactions,
    format_money,
    unique_service_charge_total,
)


@dataclass
class PackageFinancialSemantics:
    printed_page_totals: list[str] = field(default_factory=list)
    derived_page_service_totals: list[str] = field(default_factory=list)
    unique_package_service_charges: str | None = None
    amount_paid: str | None = None
    opening_balance: str | None = None
    ending_balance: str | None = None
    adjustments: str | None = None
    total_charges: str | None = None
    contract_mismatch: bool = False
    reasons: list[str] = field(default_factory=list)
    dedupe: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "printed_page_total": list(self.printed_page_totals),
            "derived_page_service_total": list(self.derived_page_service_totals),
            "unique_package_service_charges": self.unique_package_service_charges,
            "amount_paid": self.amount_paid,
            "opening_balance": self.opening_balance,
            "ending_balance": self.ending_balance,
            "adjustments": self.adjustments,
            "total_charges": self.total_charges,
            "contract_mismatch": self.contract_mismatch,
            "reasons": list(self.reasons),
            "dedupe": dict(self.dedupe),
        }


def build_package_financials(
    *,
    transactions: list[FinancialTransaction],
    printed_page_totals: list[object] | None = None,
    derived_page_totals: list[object] | None = None,
    amount_paid: object = None,
    opening_balance: object = None,
    ending_balance: object = None,
    adjustments: object = None,
    golden_total_charges: object = None,
) -> PackageFinancialSemantics:
    """Canonical total_charges = sum of unique SERVICE_CHARGE transactions."""
    deduped = dedupe_transactions(transactions)
    service_total = unique_service_charge_total(deduped.canonical)

    def _fmt(value: object) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return format_money(value)
        text = str(value).strip()
        return text or None

    out = PackageFinancialSemantics(
        printed_page_totals=[str(x) for x in (printed_page_totals or []) if x is not None],
        derived_page_service_totals=[
            str(x) for x in (derived_page_totals or []) if x is not None
        ],
        unique_package_service_charges=format_money(service_total),
        amount_paid=_fmt(amount_paid),
        opening_balance=_fmt(opening_balance),
        ending_balance=_fmt(ending_balance),
        adjustments=_fmt(adjustments),
        total_charges=format_money(service_total),
        reasons=[
            "TOTAL_CHARGES_EQUALS_UNIQUE_SERVICE_CHARGES",
            "EXCLUDED_OPENING_ENDING_BALANCE_PAYMENTS",
        ],
        dedupe=deduped.to_dict(),
    )

    # Ending balance must never be promoted as total_charges.
    if out.ending_balance and out.total_charges == out.ending_balance:
        # Coincidence is allowed numerically, but record the role separation.
        out.reasons.append("ENDING_BALANCE_VALUE_EQUALS_CHARGES_BUT_DISTINCT_ROLE")

    golden = _fmt(golden_total_charges)
    if golden and golden != out.total_charges:
        # Do not force extraction to match an undefined/wrong label.
        out.contract_mismatch = True
        out.reasons.append("CONTRACT_MISMATCH_GOLDEN_TOTAL_CHARGES")
    return out


def exclude_non_charge_roles(tx: FinancialTransaction) -> bool:
    return tx.transaction_type is TransactionType.SERVICE_CHARGE
