"""Unit tests for v11.2 name conflict relief (token order + glued MI)."""

from packages.candidate_reconciliation.reconciler import (
    _names_differ_by_glued_middle_initial,
    _names_differ_by_token_order,
    prefer_name_canonical_token_order,
    prefer_name_with_optional_middle_initial,
    values_conflict_equivalent,
)


def test_glued_middle_initial_cl_vs_l():
    assert _names_differ_by_glued_middle_initial(
        "DEPONTE DESIRAE CL", "DEPONTE DESIRAE L"
    )
    assert values_conflict_equivalent(
        "patient_name", "DEPONTE DESIRAE CL", "DEPONTE DESIRAE L"
    )
    preferred = prefer_name_with_optional_middle_initial(
        "DEPONTE DESIRAE CL", ["DEPONTE DESIRAE L"]
    )
    assert preferred == "DEPONTE DESIRAE L"


def test_glued_middle_initial_cp_vs_p():
    assert _names_differ_by_glued_middle_initial(
        "VISORIA SHYENNE CP", "VISORIA SHYENNE P"
    )
    preferred = prefer_name_with_optional_middle_initial(
        "VISORIA SHYENNE CP", ["VISORIA SHYENNE P"]
    )
    assert preferred == "VISORIA SHYENNE P"


def test_last_first_token_order_equivalence():
    assert _names_differ_by_token_order("CHANG SHERRILEE", "SHERRILEE L CHANG")
    assert values_conflict_equivalent(
        "patient_name", "CHANG SHERRILEE", "SHERRILEE L CHANG"
    )
    preferred = prefer_name_canonical_token_order(
        "CHANG SHERRILEE", ["SHERRILEE L CHANG"]
    )
    assert preferred == "SHERRILEE L CHANG"


def test_spinney_token_order():
    assert _names_differ_by_token_order("SPINNEY CHARLES A", "CHARLES A SPINNEY")
    preferred = prefer_name_canonical_token_order(
        "SPINNEY CHARLES A", ["CHARLES A SPINNEY"]
    )
    assert preferred == "CHARLES A SPINNEY"


def test_smithwick_token_order_with_confusable():
    # SMITHWTCK vs SMITHWICK differs by T↔I confusable on the surname token.
    assert _names_differ_by_token_order(
        "SMITHWTCK CYNTHIA L", "CYNTHIA L SMITHWICK"
    )
    assert values_conflict_equivalent(
        "insured_name", "SMITHWICK CYNTHIA L", "CYNTHIA L SMITHWICK"
    )


def test_name_digit_zero_as_o_and_optional_mi():
    assert values_conflict_equivalent("patient_name", "LO DANNY", "L0 DANNY B")
