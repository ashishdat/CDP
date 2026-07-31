"""Claim-level reconciliation: service-line charges must sum to the
claim's total charge. Compared in cents (`Decimal.quantize`) to avoid
float rounding noise."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from packages.domain.claim import Claim

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    expected_total: Decimal
    actual_total: Decimal | None
    reason: str | None = None


def check_service_line_total_matches_claim_total(claim: Claim) -> ReconciliationResult:
    line_amounts = [
        line.charge_amount for line in claim.service_lines if line.charge_amount is not None
    ]
    computed_total = sum(line_amounts, Decimal(0)).quantize(CENTS)

    if claim.total_charge_amount is None:
        return ReconciliationResult(
            ok=False,
            expected_total=computed_total,
            actual_total=None,
            reason="claim.total_charge_amount is missing",
        )

    claimed_total = claim.total_charge_amount.quantize(CENTS)
    if computed_total != claimed_total:
        return ReconciliationResult(
            ok=False,
            expected_total=computed_total,
            actual_total=claimed_total,
            reason=(
                f"service lines sum to {computed_total}, but claim.total_charge_amount is "
                f"{claimed_total}"
            ),
        )
    return ReconciliationResult(ok=True, expected_total=computed_total, actual_total=claimed_total)
