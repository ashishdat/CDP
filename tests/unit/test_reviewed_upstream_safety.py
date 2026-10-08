"""Safety fixes reviewed from origin/feature/cdp-v3 at de373ac0."""
import pytest

from packages.claim_evidence.line_sum_authority import is_implausible_corroborator
from packages.extraction_recovery.charge_azure_di_residual import is_charge_local_residual
from packages.product_gates.accuracy_accept_policy import (
    evaluate_critical_accept,
    evaluate_insured_id_accept,
    evaluate_insured_name_accept,
)


def test_real_surname_is_not_a_fill_in_instruction():
    assert evaluate_insured_name_accept('FILLINGIM, CARMEN G').allow_auto
    assert not evaluate_insured_name_accept('PLEASE FILL IN').allow_auto


@pytest.mark.parametrize('value', ['0000000', '000-000-000', "1a. INSURED'S 1.D. NUMBER"])
def test_placeholder_member_identifiers_remain_blocked(value):
    assert not evaluate_insured_id_accept(value).allow_auto


@pytest.mark.parametrize('value', ['A000000', '0000374350', '900265865'])
def test_real_identifiers_are_not_rejected_for_containing_zeros(value):
    assert evaluate_insured_id_accept(value).allow_auto


@pytest.mark.parametrize('value', ['0195-09-03', '01950903', '1 1 1'])
def test_junk_dob_year_cannot_pass_critical_acceptance(value):
    assert not evaluate_critical_accept('patient_dob', value).allow_auto


@pytest.mark.parametrize('value', ['1995-09-03', '08/16/1993', '08161993'])
def test_real_dob_representation_keeps_existing_downstream_validation(value):
    assert evaluate_critical_accept('patient_dob', value).allow_auto


@pytest.mark.parametrize('gap', ['LINE_SUM_UNCORROBORATED', 'EVIDENCE_POLICY_GAP', 'CALIBRATION_HITL'])
def test_missing_charge_evidence_can_request_recovery_without_granting_acceptance(gap):
    assert is_charge_local_residual(field_name='total_charge', gap_class=gap,
                                   local_accepted=False)
    assert not is_charge_local_residual(field_name='total_charge', gap_class=gap,
                                       local_accepted=True)


@pytest.mark.parametrize('value,total', [('182500', '1825.00'), ('1825.00', '182500')])
def test_large_decimal_scale_rival_is_not_discarded_as_form_noise(value, total):
    assert not is_implausible_corroborator(value, total)


def test_labels_without_matching_accepted_fields_are_not_zero_false_accepts(tmp_path):
    import json
    from packages.evaluation.agent_gt_score import score_merged_against_agent_gt

    truth = tmp_path / 'truth.json'
    truth.write_text(json.dumps({'claims': {'labeled': {'fields': {
        'patient_name': {'value': 'SMITH JOHN', 'confidence': 'GOLD'}}}}}))
    report = score_merged_against_agent_gt({'unlabeled': {
        'disposition': 'TRUE_STP', 'fields': {'patient_name': {
            'value': 'JONES MARY', 'disp': 'AUTO_ACCEPTED'}}}}, truth,
        apply_quarantine=False)
    assert report['status'] == 'NO_OVERLAP'
    assert report['false_accepts'] is None
    assert report['accepted_field_precision'] is None


@pytest.mark.parametrize('status', ['NO_OVERLAP', 'UNKNOWN', 'SKIPPED'])
def test_unqualified_accuracy_report_cannot_pass_product_gate(monkeypatch, status):
    from packages.evaluation import agent_gt_score
    from packages.product_gates.similar_sample_gate import evaluate_similar_sample_gate

    monkeypatch.setattr(agent_gt_score, 'score_merged_against_agent_gt',
                        lambda *a, **kw: {'status': status, 'false_accepts': None})
    result = evaluate_similar_sample_gate({'claim': {'disposition': 'TRUE_STP'}},
                                         allow_missing_manifest=True)
    assert not result.pass_gate
