
from tests.unit.test_uat_extraction_acceptance import ASSETS, candidate, page
from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance, type_support
from workers.unstructured_extraction.observed_type import resolve_observed_type
from workers.unstructured_extraction.uat_cases import decide_case
from workers.unstructured_extraction.uat_recovery_rules import confirm_mask_matches, name_similarity
from workers.unstructured_extraction.uat_validation import valid_scalar


def masked(value='XXXXXXXX1234', matched=True):
    return {'value': value, 'raw_confidence': .95, 'last4_match_verified': matched,
            'field_association': 'MASKED_ID_SOURCE_PATTERN', 'evidence_reference': 'page:1:mask',
            'mask_basis': 'EXPLICIT_EIGHT_MASK_CHARACTERS'}


def aadhaar(items):
    return ExtractionAcceptance().decide('AADHAAR', [page('Government of India Aadhaar')],
        expected_pages=1, assets=ASSETS, candidates={'patient_name': [candidate('Sivakumar')],
            'patient_dob': [candidate('04/01/1979')], 'identity_number_masked': items})


def test_masked_output_requires_format_and_last4_match():
    result = aadhaar([masked()])
    assert result['extraction_stp_eligible']
    assert 'identity_number_masked' in result['extracted_fields']
    assert 'identity_number' not in result['extracted_fields']
    assert result['provided_roles'] == ['identity:any', 'identity:aadhaar']
    assert not aadhaar([masked(matched=False)])['extraction_stp_eligible']
    assert not aadhaar([masked('1234')])['extraction_stp_eligible']


def test_different_masked_suffixes_remain_conflicting():
    assert 'CONFLICTING_VALUES:identity_number_masked' in aadhaar(
        [masked(), masked('XXXXXXXX5678')])['reason_codes']


def test_repeated_same_evidence_is_not_independent_suffix_match():
    item = dict(masked(), suffix='1234')
    assert not confirm_mask_matches([item, dict(item)])[0]['last4_match_verified']
    assert confirm_mask_matches([item], ['1234'])[0]['last4_match_verified']


def test_vid_is_separate_from_masked_aadhaar():
    result = ExtractionAcceptance().decide('AADHAAR', [page('Aadhaar VID: 9120 5094 2283 2939')],
        expected_pages=1, assets=ASSETS, candidates={})
    assert result['value_representations']['aadhaar_vid'][0]['not_aadhaar_number']
    assert 'identity_number' not in result['extracted_fields']
    assert not valid_scalar('identity_number', '9120509422832939')


def test_filename_never_confirms_type_alone():
    spec = ExtractionAcceptance().config['profiles']['MER']
    assert not type_support([page('unrelated material')], spec, kind='MER', filename='case_MER.pdf')
    evidence = type_support([page('Medical Exam ation Report')], spec, kind='MER', filename='case_MER.pdf')
    assert any(item['basis'] == 'FUZZY_CONTENT_ANCHOR' for item in evidence)
    assert any(item['basis'] == 'SUPPORTING_FILENAME_HINT' for item in evidence)


def test_waveforms_do_not_make_tmt_without_stress_evidence():
    spec = ExtractionAcceptance().config['profiles']['TMT']
    visual = {'waveforms': [{'page': 1, 'basis': 'GRID_AND_ECG_LEAD_MARKERS'}]}
    assert not type_support([page('V1 V2 V3')], spec, kind='TMT', filename='case_TMT.pdf', visual=visual)
    assert type_support([page('BRUCE V1 V2 V3')], spec, kind='TMT', visual=visual)


def test_single_word_names_and_full_name_fuzzy_comparison():
    assert valid_scalar('patient_name', 'Sivakumar')
    assert not valid_scalar('patient_name', 'Male')
    assert name_similarity('Mr. Chhaya Kanta Gouda', 'Chhayakanta Gouda') >= .9
    assert name_similarity('Jane Smith', 'Jane Brown') < .9
    assert name_similarity('CH. KISHOR','Chakali Kishor') >= .9
    assert name_similarity('Suresh Jagtap','Suresh Khandu Jagtap') >= .9
    assert name_similarity('Suresh Kumar Jagtap','Suresh Khandu Jagtap') < .9


def test_medical_name_mismatch_blocks_instead_of_replacing_value():
    result = ExtractionAcceptance().decide('PATH', [page('CBC')], expected_pages=1, assets=ASSETS,
        candidates={'patient_name': [candidate('Jane Brown')], 'report_date': [candidate('27/06/2026')]},
        known_names=['Jane Smith'])
    assert 'CASE_NAME_MISMATCH:patient_name' in result['reason_codes']
    assert result['extracted_fields']['patient_name']['value'] == 'Jane Brown'


def test_required_case_reference_cannot_be_silently_skipped():
    result = ExtractionAcceptance().decide('PATH', [page('CBC')], expected_pages=1, assets=ASSETS,
        candidates={'patient_name': [candidate('Jane Brown')], 'report_date': [candidate('27/06/2026')]},
        case_verification_required=True)
    assert 'CASE_NAME_REFERENCE_UNAVAILABLE:patient_name' in result['reason_codes']


def test_local_portrait_routes_without_new_cloud_calls_and_flags_supply():
    assets = [{'path': 'portrait.png', 'page': 1}]
    result = resolve_observed_type('DRIVING_LICENSE', records=[], assets=assets, sources=[(1, [])],
        candidates={}, policy=ExtractionAcceptance().config, successful_di_pages=[],
        local_portraits=[{'page': 1, 'basis': 'LOCAL_FACE_DETECTION'}])
    assert result['effective_type'] == 'PERSON_PHOTO'
    case = decide_case([{'id': 'case/photo', 'declared_type': 'DRIVING_LICENSE',
        'effective_type': 'PERSON_PHOTO', 'decision': {'extraction_stp_eligible': True,
            'provided_roles': ['image_asset'], 'extracted_fields': {}}}])
    assert case['supply_flags'] == ['LICENCE_NOT_SUPPLIED']
    assert not case['case_complete']
