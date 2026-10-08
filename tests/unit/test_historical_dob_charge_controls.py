from packages.product_gates.accuracy_accept_policy import evaluate_patient_dob_accept
from packages.claim_evidence.line_sum_authority import is_implausible_charge_total,is_implausible_corroborator


def test_september_valid_zero_month_fix_is_still_present():
    assert evaluate_patient_dob_accept('08/16/1993').allow_auto
    assert evaluate_patient_dob_accept('08161993').allow_auto
    assert not evaluate_patient_dob_accept('01950903').allow_auto


def test_large_glue_is_evidence_only_when_related_to_observed_total():
    assert is_implausible_charge_total('182500.00')
    assert not is_implausible_corroborator('182500.00','1825.00')
    assert is_implausible_corroborator('182500.00','450.00')
