from tests.unit.test_uat_binding_v5 import layout
from workers.unstructured_extraction.uat_binding_v6 import recover
from workers.unstructured_extraction.uat_evidence import date_role
from workers.unstructured_extraction.uat_recovery_rules import name_similarity


def date_candidate(value, score=.7, page=1, mapping=''):
    return {'value': value, 'raw_confidence': score, 'page_number': page,
            'field_association': 'DIRECT_LABEL', 'mapping_record': mapping,
            'bounding_box': {'x0': 50, 'y0': 50, 'x1': 170, 'y1': 70}}


def test_reordered_initials_and_fused_given_name_keep_all_letters():
    assert name_similarity('DEVKUMAR K N', 'K N DEV KUMAR') >= .9
    assert name_similarity('DEVKUMAR K N', 'K M DEV KUMAR') < .9
    assert name_similarity('DEVKUMAR K', 'K N DEV KUMAR') < .9


def test_printed_date_does_not_become_report_date():
    assert date_role('Print Date ') == 'print_date'
    assert date_role('Printed on ') == 'print_date'


def test_same_location_low_ocr_is_excluded_only_with_new_bounded_agreement():
    old = date_candidate('27-Jan-2026', .2)
    new = date_candidate('27-Jun-2026', .96, mapping='llm_v6_date_conflict_p009.json')
    result = recover('TMT', [], {'report_date': [old, new]})
    assert result['report_date'][0]['role_conflict']
    assert result['report_date'][0]['replacement_value'] == '27-Jun-2026'
    assert new['raw_confidence'] == .96


def test_different_pages_or_high_conflicting_values_stay_in_review():
    old = date_candidate('27-Jan-2026', .92)
    new = date_candidate('27-Jun-2026', .96, mapping='llm_v6_date_conflict_p009.json')
    other_page = date_candidate('27-Jul-2026', .3, page=2)
    recover('TMT', [], {'report_date': [old, new, other_page]})
    assert not old.get('role_conflict')
    assert not other_page.get('role_conflict')


def test_model_alone_without_ocr_threshold_cannot_supersede_date():
    old = date_candidate('27-Jan-2026', .2)
    new = date_candidate('27-Jun-2026', .79, mapping='llm_v6_date_conflict_p009.json')
    recover('TMT', [], {'report_date': [old, new]})
    assert not old.get('role_conflict')


def test_certificate_declaration_year_discrepancy_is_held_not_rewritten():
    declaration = layout([(10, 'Declaration by Life Assured'), (60, 'Date: 26/06/2026')], kind='MER')
    exam = {**date_candidate('26/06/2016', .92), 'field_association': 'CERTIFICATE_DATE_POSITION'}
    recover('MER', [declaration], {'examination_date': [exam]})
    assert exam['role_conflict']
    assert exam['value'] == '26/06/2016'


def test_existing_bound_diagnosis_does_not_get_a_partial_duplicate():
    page = layout([(10, 'Diagnosis Information:'), (40, 'Normal Sinus Rhythm')], kind='ECG')
    old = {'value': 'Normal Sinus Rhythm', 'raw_confidence': .95, 'field_association': 'DIRECT_LABEL'}
    result = recover('ECG', [page], {'ecg_interpretation': [old]})
    assert result['ecg_interpretation'] == [old]


def test_ecg_pr_measurement_cannot_displace_complete_name():
    page = layout([(10, 'MARY DOE PR : 157 ms Normal ECG')], kind='ECG')
    full = {'value': 'JANE MARY DOE', 'raw_confidence': .99, 'page_number': 1,
            'field_association': 'CASE_NAME_SOURCE_MATCH',
            'bounding_box': {'x0': 10, 'y0': 10, 'x1': 200, 'y1': 30}}
    contaminated = {**full, 'value': 'JANE MARY DOE PR',
                    'bounding_box': {'x0': 10, 'y0': 10, 'x1': 230, 'y1': 30}}
    recover('ECG', [page], {'patient_name': [full, contaminated]})
    assert contaminated['role_conflict']
    assert not full.get('role_conflict')


def test_separate_declaration_date_row_also_checks_certificate_year():
    page = layout([(10, 'Declaration by Life Assured'), (50, '26/06/2026'), (70, 'Date:')], kind='MER')
    exam = {**date_candidate('26/06/2016', .92), 'field_association': 'CERTIFICATE_DATE_POSITION'}
    recover('MER', [page], {'examination_date': [exam]})
    assert exam['role_conflict']
