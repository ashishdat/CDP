"""Date relationship validation. Dates arrive already normalized to ISO
(`YYYY-MM-DD`) by `workers.standard_form_extraction.field_processors` --
this module checks *relationships between* dates, not date syntax."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

MAX_REASONABLE_PATIENT_AGE_YEARS = 130


@dataclass(frozen=True)
class DateCheckResult:
    ok: bool
    reason: str | None = None


def check_not_future(value: date, today: date | None = None) -> DateCheckResult:
    reference = today or date.today()  # noqa: DTZ011 -- claim dates are calendar dates, not tz-aware
    if value > reference:
        return DateCheckResult(ok=False, reason=f"{value.isoformat()} is in the future")
    return DateCheckResult(ok=True)


def check_range_order(date_from: date, date_to: date) -> DateCheckResult:
    if date_from > date_to:
        return DateCheckResult(
            ok=False,
            reason=f"date_from {date_from.isoformat()} is after date_to {date_to.isoformat()}",
        )
    return DateCheckResult(ok=True)


def check_birth_date_precedes_service_date(dob: date, service_date: date) -> DateCheckResult:
    if dob > service_date:
        return DateCheckResult(
            ok=False,
            reason=(
                f"date of birth {dob.isoformat()} is after service date "
                f"{service_date.isoformat()}"
            ),
        )
    age_years = (service_date - dob).days / 365.25
    if age_years > MAX_REASONABLE_PATIENT_AGE_YEARS:
        return DateCheckResult(
            ok=False,
            reason=f"implied patient age at service ({age_years:.0f}y) exceeds plausible range",
        )
    return DateCheckResult(ok=True)


def check_within_timely_filing_window(
    service_date: date, submission_date: date, max_days: int = 365
) -> DateCheckResult:
    if submission_date < service_date:
        return DateCheckResult(ok=False, reason="submission date precedes service date")
    if (submission_date - service_date) > timedelta(days=max_days):
        return DateCheckResult(
            ok=False,
            reason=f"submission is more than {max_days} days after service date",
        )
    return DateCheckResult(ok=True)
