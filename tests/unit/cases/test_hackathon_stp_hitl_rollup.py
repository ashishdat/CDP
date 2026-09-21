"""STP / HITL rollup must not conflate infra failures with field-ink HITL."""

from __future__ import annotations

from scripts.run_hackathon_1000_cascade import _rollup_scope


def _row(
    *,
    disposition: str,
    true_stp: bool = False,
    completed: bool = False,
    registration_ok: bool = False,
    hitl_track: str | None = None,
) -> dict:
    return {
        "disposition": disposition,
        "true_stp": true_stp,
        "completed": completed,
        "registration_ok": registration_ok,
        "hitl_track": hitl_track,
    }


def test_rollup_primary_rates_use_completed_denominator() -> None:
    rows = [
        _row(
            disposition="TRUE_STP",
            true_stp=True,
            completed=True,
            registration_ok=True,
        ),
        _row(
            disposition="TRUE_STP",
            true_stp=True,
            completed=True,
            registration_ok=True,
        ),
        _row(
            disposition="HITL",
            completed=True,
            registration_ok=True,
            hitl_track="FIELD_INK",
        ),
        _row(disposition="REGISTRATION_FAILED"),
        _row(disposition="STAGE_FAILURE"),
    ]
    roll = _rollup_scope(rows)
    assert roll["n"] == 5
    assert roll["completed"] == 3
    assert roll["true_stp"] == 2
    assert roll["field_ink_hitl"] == 1
    assert roll["infra_failures"] == 2
    # Primary rates: of completed, not of all.
    assert roll["true_stp_rate"] == round(2 / 3, 6)
    assert roll["hitl_rate"] == round(1 / 3, 6)
    # Misreport that conflates infra into HITL.
    assert roll["misreported_hitl_as_n_minus_stp"] == round(3 / 5, 6)
    assert roll["hitl_rate"] != roll["misreported_hitl_as_n_minus_stp"]


def test_rollup_excludes_unstructured_reg_from_field_hitl() -> None:
    rows = [
        _row(
            disposition="TRUE_STP",
            true_stp=True,
            completed=True,
            registration_ok=True,
        ),
        # Legacy bug: unstructured DI marked disposition=HITL + completed.
        _row(
            disposition="HITL",
            completed=True,
            registration_ok=False,
            hitl_track="UNSTRUCTURED_DI",
        ),
        _row(disposition="REGISTRATION_FAILED"),
    ]
    roll = _rollup_scope(rows)
    assert roll["completed"] == 1
    assert roll["true_stp"] == 1
    assert roll["field_ink_hitl"] == 0
    assert roll["true_stp_rate"] == 1.0
    assert roll["hitl_rate"] == 0.0


def test_rollup_stp_plus_field_hitl_equals_completed() -> None:
    rows = [
        _row(
            disposition="TRUE_STP",
            true_stp=True,
            completed=True,
            registration_ok=True,
        ),
        _row(
            disposition="HITL",
            completed=True,
            registration_ok=True,
            hitl_track="FIELD_INK",
        ),
        _row(
            disposition="HITL",
            completed=True,
            registration_ok=True,
            hitl_track="FIELD_INK",
        ),
        _row(disposition="REGISTRATION_FAILED"),
        _row(disposition="INCOMPLETE", registration_ok=True),
    ]
    roll = _rollup_scope(rows)
    assert roll["true_stp"] + roll["field_ink_hitl"] == roll["completed"]
