"""Reconciliation report: summarizes deterministic validation results for
a claim into pass/fail counts plus the specific financial reconciliation
outcome -- what an operator checks before considering output final."""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.domain.claim import Claim
from packages.domain.enums import ValidationStatus
from packages.domain.validation import ValidationResult
from packages.validation_rules.reconciliation import (
    ReconciliationResult,
    check_service_line_total_matches_claim_total,
)


@dataclass
class ReconciliationReport:
    claim_id: str
    valid_count: int = 0
    invalid_count: int = 0
    needs_review_count: int = 0
    financial: ReconciliationResult | None = None
    failures: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.invalid_count == 0 and self.needs_review_count == 0


def build_reconciliation_report(
    claim: Claim, validation_results: list[ValidationResult]
) -> ReconciliationReport:
    report = ReconciliationReport(claim_id=str(claim.claim_id))
    for result in validation_results:
        if result.status == ValidationStatus.VALID:
            report.valid_count += 1
        elif result.status == ValidationStatus.NEEDS_REVIEW:
            report.needs_review_count += 1
            report.failures.append(f"{result.field_name}: {result.message or result.rule_name}")
        elif result.status == ValidationStatus.INVALID:
            report.invalid_count += 1
            report.failures.append(f"{result.field_name}: {result.message or result.rule_name}")

    report.financial = check_service_line_total_matches_claim_total(claim)
    return report
