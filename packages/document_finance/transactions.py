"""Transaction identity, fingerprints, and cumulative-statement deduplication."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class TransactionType(StrEnum):
    OPENING_BALANCE = "OPENING_BALANCE"
    SERVICE_CHARGE = "SERVICE_CHARGE"
    PAYMENT = "PAYMENT"
    ADJUSTMENT = "ADJUSTMENT"
    ENDING_BALANCE = "ENDING_BALANCE"
    UNKNOWN = "UNKNOWN"


def parse_money(value: object) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    neg = "(" in raw or raw.startswith("-") or raw.upper().endswith("CR")
    cleaned = re.sub(r"[^0-9.]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    if neg and amount > 0:
        amount = -amount
    return amount


def format_money(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


def _norm_text(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


@dataclass
class FinancialTransaction:
    date: str | None = None
    description: str | None = None
    procedure_code: str | None = None
    amount: Decimal | None = None
    balance: Decimal | None = None
    transaction_type: TransactionType = TransactionType.UNKNOWN
    fee: Decimal | None = None
    quantity: Decimal | None = None
    line_total: Decimal | None = None
    provider_id: str | None = None
    patient_id: str | None = None
    page_index: int | None = None
    row_index: int | None = None
    fingerprint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def ensure_fingerprint(self) -> str:
        if self.fingerprint:
            return self.fingerprint
        # Business identity first. When date is absent, page/row lineage is
        # required so distinct package service lines are not collapsed.
        parts = [
            _norm_text(self.provider_id),
            _norm_text(self.patient_id),
            _norm_text(self.date),
            _norm_text(self.procedure_code or self.description),
            format_money(self.amount) if self.amount is not None else "",
        ]
        if not _norm_text(self.date):
            parts.append(f"P{self.page_index}")
            parts.append(f"R{self.row_index}")
        payload = "|".join(parts)
        self.fingerprint = hashlib.sha256(payload.encode()).hexdigest()[:24]
        return self.fingerprint

    def to_dict(self) -> dict[str, Any]:
        self.ensure_fingerprint()
        return {
            "date": self.date,
            "description": self.description,
            "procedure_code": self.procedure_code,
            "amount": format_money(self.amount) if self.amount is not None else None,
            "balance": format_money(self.balance) if self.balance is not None else None,
            "transaction_type": self.transaction_type.value,
            "fee": format_money(self.fee) if self.fee is not None else None,
            "quantity": str(self.quantity) if self.quantity is not None else None,
            "line_total": (
                format_money(self.line_total) if self.line_total is not None else None
            ),
            "provider_id": self.provider_id,
            "patient_id": self.patient_id,
            "page_index": self.page_index,
            "row_index": self.row_index,
            "fingerprint": self.fingerprint,
            "raw": dict(self.raw),
        }


@dataclass
class DedupResult:
    canonical: list[FinancialTransaction]
    duplicates: list[dict[str, Any]]
    removed_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical": [t.to_dict() for t in self.canonical],
            "duplicates": list(self.duplicates),
            "removed_count": self.removed_count,
        }


def classify_ledger_row(
    *,
    description: str | None,
    amount: Decimal | None,
    is_bottom_total: bool = False,
) -> TransactionType:
    text = (description or "").upper()
    if is_bottom_total or re.search(r"\b(ENDING\s+BALANCE|BALANCE\s+DUE|TOTAL\s+BALANCE)\b", text):
        return TransactionType.ENDING_BALANCE
    if re.search(r"BALANCE\s+FORWARD|OPENING\s+BALANCE|PRIOR\s+BALANCE", text):
        return TransactionType.OPENING_BALANCE
    if amount is not None and amount < 0:
        return TransactionType.PAYMENT
    if re.search(r"\b(PMT|PAYMENT|ACH|VISA|MC|CHECK|CARD)\b", text):
        return TransactionType.PAYMENT
    if re.search(r"\b(ADJUST|WRITE[\s-]?OFF|CREDIT)\b", text):
        return TransactionType.ADJUSTMENT
    if amount is not None and amount > 0:
        return TransactionType.SERVICE_CHARGE
    return TransactionType.UNKNOWN


def dedupe_transactions(
    transactions: list[FinancialTransaction],
) -> DedupResult:
    """Keep one canonical copy per business fingerprint; retain dup lineage."""
    by_fp: dict[str, FinancialTransaction] = {}
    duplicates: list[dict[str, Any]] = []
    for tx in transactions:
        fp = tx.ensure_fingerprint()
        if fp not in by_fp:
            by_fp[fp] = tx
            continue
        duplicates.append(
            {
                "fingerprint": fp,
                "kept_page": by_fp[fp].page_index,
                "kept_row": by_fp[fp].row_index,
                "dup_page": tx.page_index,
                "dup_row": tx.row_index,
                "amount": format_money(tx.amount) if tx.amount is not None else None,
            }
        )
    return DedupResult(
        canonical=list(by_fp.values()),
        duplicates=duplicates,
        removed_count=len(duplicates),
    )


def unique_service_charge_total(
    transactions: list[FinancialTransaction],
) -> Decimal:
    total = Decimal("0.00")
    for tx in transactions:
        if tx.transaction_type is not TransactionType.SERVICE_CHARGE:
            continue
        amount = tx.line_total if tx.line_total is not None else tx.amount
        if amount is None or amount <= 0:
            continue
        total += amount
    return total.quantize(Decimal("0.01"))
