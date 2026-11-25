import copy

import pytest

from tests.unit.test_uat_extraction_acceptance import ASSETS, candidate, page
from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance
from workers.unstructured_extraction.uat_vision_recovery import crop_valid, propose

ASSET = {'path': 'test_source.png', 'sha256': 'source-sha', 'width': 1000, 'height': 1000, 'page': 1}
BOX = [.1, .1, .9, .3]
REF = {'document_id': 'case/other', 'value': 'Jane Doe', 'raw_confidence': .95,
       'source_verified': True, 'evidence_reference': 'page:1:name'}


def proposal(name='patient_name', value='Jane Doe', citation='Patient name: Jane Doe', **kwargs):
    result = {'status': 'SUCCESS', 'source_image': ASSET['path'], 'crop_fraction': BOX, 'provider': 'test_vision'}
    field = {'field_name': name, 'value': value, 'confidence': .999, 'citation': citation}
    record = kwargs.pop('record', {'id': 'case/doc', 'verified_name_sources': [REF]})
    job = {'id': 'case/doc/crop1', 'image': ASSET['path'], 'crop_fraction': BOX, 'fields': {name: 'exact visible value'},
           'localization_basis': 'SOURCE_INSPECTED_FIELD_REGION'}
    result.update(kwargs.pop('result_updates', {})); job.update(kwargs.pop('job_updates', {}))
    field.update(kwargs.pop('field_updates', {}))
    return propose(field, result, record=record, asset=ASSET, evidence_path='crop_result.json', authorized_job=job)


def test_exact_other_document_name_is_a_proposal_not_an_ocr_witness():
    item = proposal()
    assert item['review_status'] == 'CORROBORATED_REVIEW_REQUIRED'
    assert item['ocr_confidence_available'] is False
    assert item['raw_confidence'] == 0
    assert item['value'] == 'Jane Doe'
    assert item['bounding_box'] == {'x0': 100, 'y0': 100, 'x1': 900, 'y1': 300}
    assert not item['auto_accept_eligible']


def test_fuzzy_match_preserves_reading_and_marks_spelling_uncertainty():
    item = proposal(value='Janne Doe', citation='Patient name: Janne Doe')
    assert item['value'] == 'Janne Doe'
    assert 'FUZZY_MATCH_SPELLING_REQUIRES_REVIEW' in item['validation_issues']
    assert item['review_status'] == 'REVIEW_REQUIRED'


def test_self_document_reference_cannot_corroborate():
    item = proposal(record={'id': 'case/doc', 'verified_name_sources': [{**REF, 'document_id': 'case/doc'}]})
    assert not item['corroborating_name_sources']
    assert item['review_status'] == 'REVIEW_REQUIRED'


@pytest.mark.parametrize(('name','value','citation','issue'), [
    ('patient_name', 'John Roe', 'Patient name: John Roe', 'OTHER_DOCUMENT_NAME_MISMATCH'),
    ('patient_name', 'Jane Doe', "Father's name: Jane Doe", 'PARENT_OR_DOCTOR_IS_NOT_PATIENT'),
    ('report_date', '31/02/2026', 'Report date: 31/02/2026', 'INVALID_FORMAT_OR_LABEL_TEXT'),
    ('report_date', '24/06/2026', 'Registered on: 24/06/2026', 'SOURCE_DATE_ROLE_MISMATCH'),
    ('identity_number', '1234567890123456', 'VID: 1234567890123456', 'VID_IS_NOT_IDENTITY_NUMBER'),
    ('ecg_interpretation', 'Normal ECG', 'Inferred from waveform', 'INFERRED_CLINICAL_INTERPRETATION_FORBIDDEN'),
])
def test_wrong_format_role_or_inference_is_rejected(name, value, citation, issue):
    item = proposal(name, value, citation)
    assert issue in item['validation_issues']
    assert item['review_status'] == 'REJECTED'


def test_masked_source_does_not_allow_full_number_invention():
    item = proposal('identity_number', '234567890123', 'Aadhaar: 234567890123',
                    record={'id': 'case/doc', 'masked_candidates': [{'value': 'XXXXXXXX0123'}]})
    assert item['review_status'] == 'REJECTED'
    assert 'FULL_NUMBER_FROM_MASKED_SOURCE_FORBIDDEN' in item['validation_issues']


def test_short_year_never_gets_a_century_from_another_document():
    item = proposal('report_date', '24/06/26', 'Report date: 24/06/26')
    assert item['value'] == '24/06/26'
    assert 'AMBIGUOUS_DATE_YEAR' in item['validation_issues']


@pytest.mark.parametrize('box', [[0, 0, 1, 1], [.9, .1, .1, .2], [0, 0, float('nan'), .2], [True, 0, .2, .2]])
def test_invalid_or_full_page_crop_not_sent_to_vision_path(box):
    assert not crop_valid(box)


def test_image_or_crop_mismatch_rejects_unbound_provider_record():
    assert proposal(result_updates={'source_image': 'other.png'})['review_status'] == 'REJECTED'
    assert proposal(job_updates={'crop_fraction': [.2, .2, .5, .5]})['review_status'] == 'REJECTED'


def test_abstention_does_not_create_empty_or_invented_candidate():
    assert proposal(field_updates={'value': None, 'insufficient_evidence': True}) is None


def test_gate_cannot_be_bypassed_by_model_score_or_candidate_flags():
    item = proposal()
    item.update(raw_confidence=1.0, auto_accept_eligible=True)
    accept = ExtractionAcceptance()
    accept.config = copy.deepcopy(accept.config)
    accept.config['profiles']['PATH']['required_fields'] = ['patient_name']
    decision = accept.decide('PATH', [page('pathology')], expected_pages=1, assets=ASSETS,
                             candidates={'patient_name': [item]}, verified_name_sources=[REF], document_id='case/doc')
    assert not decision['extraction_stp_eligible']
    assert 'patient_name' not in decision['extracted_fields']
    assert 'VISION_ONLY_ACCURACY_NOT_VALIDATED' in decision['field_diagnostics']['patient_name']['observations'][0]['exclusions']


def test_review_proposal_cannot_change_an_already_accepted_field():
    accept = ExtractionAcceptance()
    accept.config = copy.deepcopy(accept.config)
    accept.config['profiles']['PATH']['required_fields'] = ['patient_name']
    decision = accept.decide('PATH', [page('pathology')], expected_pages=1, assets=ASSETS,
                             candidates={'patient_name': [candidate('Jane Doe'), proposal(value='John Roe')]})
    assert decision['extraction_stp_eligible']
    assert decision['extracted_fields']['patient_name']['value'] == 'Jane Doe'


def test_identity_dob_can_be_corroborated_but_report_dates_cannot():
    ref = {**REF, 'field_name': 'patient_dob', 'value': '24/06/1970'}
    record = {'id': 'case/doc', 'verified_field_sources': [ref]}
    item = proposal('patient_dob', '24-Jun-1970', 'DOB: 24-Jun-1970', record=record)
    assert item['review_status'] == 'CORROBORATED_REVIEW_REQUIRED'
    assert not item['auto_accept_eligible']
    wrong = proposal('patient_dob', '24/06/1940', 'DOB: 24/06/1940', record=record)
    assert 'OTHER_DOCUMENT_IDENTITY_ATTRIBUTE_MISMATCH' in wrong['validation_issues']
    report = proposal('report_date', '24/06/1970', 'Report date: 24/06/1970', record=record)
    assert not report['corroborating_field_sources']


def test_masked_identity_shortcut_also_excludes_vision_only_values():
    accept = ExtractionAcceptance()
    accept.config = copy.deepcopy(accept.config)
    accept.config['profiles']['AADHAAR']['required_fields'] = ['identity_number']
    item = proposal('identity_number_masked', 'XXXXXXXX0123', 'Aadhaar: XXXXXXXX0123')
    item.update(field_association='MASKED_ID_SOURCE_PATTERN', last4_match_verified=True,
                mask_basis='EXPLICIT_EIGHT_MASK_CHARACTERS', raw_confidence=1.0)
    decision = accept.decide('AADHAAR', [page('government of india')], expected_pages=1, assets=ASSETS,
                             candidates={'identity_number_masked': [item]})
    assert not decision['extraction_stp_eligible']
    assert 'identity_number_masked' not in decision['extracted_fields']
