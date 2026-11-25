from types import SimpleNamespace

from packages.ocr.tesseract_adapter import parse_tsv
from packages.ocr.text_extraction import TextLine
from packages.runtime_profile.contracts import ROOT
from workers.unstructured_extraction.local_completion import LocalLayoutCompletion
from workers.unstructured_extraction.uat_policy import content_matches, load_policy, nominate_type
from workers.unstructured_extraction.uat_validation import valid_scalar


def test_ocr_quotes_do_not_swallow_following_tsv_rows():
    header = 'text\tconf\tleft\ttop\twidth\theight\n'
    rows = '"\t95\t1\t2\t3\t4\nPatient\t99\t5\t6\t7\t8\n'
    lines = parse_tsv(header + rows)
    assert [line.text for line in lines] == ['"', 'Patient']
    assert lines[1].confidence == .99


def completion():
    return LocalLayoutCompletion(profile_path=ROOT/'config/runtime_profiles/uat_local_v1.yaml',
        labels_path=ROOT/'config/uat_layout_label_aliases.yaml')


def test_every_uat_type_has_explicit_mandatory_fields():
    service = completion()
    for kind, spec in load_policy()['types'].items():
        assert set(service.services.field_policy.required_fields('UAT_' + kind)) == set(spec['required'])


def test_filename_is_only_a_nomination():
    config = load_policy()
    assert nominate_type('2QYL045260_PATH_01.PDF', 'PATH', config) == 'PATH'
    assert nominate_type('kyc_aadhaar.jpg', 'kyc_aadhaar', config) == 'AADHAAR'
    assert nominate_type('2QYL045260_PHOTO IDENTITY PROOF_01.PDF', 'PERSON_PHOTO', config) == 'IDENTITY_PROOF'
    assert nominate_type('COMPANY.jpg', 'OTHER', config) == 'OTHER'
    assert nominate_type('image.jpg', 'KYC_AADHAAR', config) == 'AADHAAR'
    assert nominate_type('image.jpg', 'kyc_pan', config) == 'PAN'
    assert not content_matches('PATH', 'unrelated document', config)
    assert content_matches('PATH', 'REPORT ON BIOCHEMISTRY', config)


def test_verified_heading_does_not_accept_missing_medical_evidence():
    page = SimpleNamespace(schema_evidence=SimpleNamespace(schema_family='UNKNOWN'), candidates={}, engine='test')
    result = completion().complete('path', [page], document_family='UAT_PATH', type_verified=True)
    assert 'DOCUMENT_ACCEPTANCE_SCHEMA_NOT_CONFIGURED' not in result['completion_reason_codes']
    assert 'DOCUMENT_SCHEMA_UNRESOLVED' not in result['completion_reason_codes']
    assert not result['claim_decision']['stp_eligible']
    assert set(result['claim_decision']['blocking_unresolved_fields']) == {'patient_name', 'report_date'}


def test_photo_completion_contract_does_not_require_identity_verification():
    page = SimpleNamespace(schema_evidence=SimpleNamespace(schema_family='NON_CLAIM'), candidates={}, engine='test')
    result = completion().complete('photo', [page], document_family='UAT_PERSON_PHOTO')
    assert not result['claim_decision']['stp_eligible']
    assert not result['claim_decision']['blocking_unresolved_fields']
    assert not result['field_decisions']


def test_day_first_dates_and_invalid_dates():
    assert valid_scalar('report_date', '29/06/2026')
    assert not valid_scalar('report_date', '31/02/2026')
    assert not valid_scalar('identity_number', 'unreadable')


def test_evaluation_route_preserves_candidate_and_real_ocr_confidence():
    service = LocalLayoutCompletion(profile_path=ROOT/'config/runtime_profiles/uat_evaluation_v1.yaml',
        labels_path=ROOT/'config/uat_layout_label_aliases.yaml')
    lines = [TextLine('Report Date:', 10, 10, 150, 30, .94),
             TextLine('29/06/2026', 160, 10, 270, 30, .73)]
    layout = service.extract_page(lines, page_number=1, width=500, height=500, engine='tesseract_psm_11')
    result = service.complete('report', [layout], document_family='UAT_PATH', type_verified=True)
    candidates = result['extracted_candidates']['report_date']
    assert candidates[0]['raw_confidence'] == .73
    field = next(f for f in result['field_decisions'] if f['field_name'] == 'report_date')
    assert field['selected_value'] == '29/06/2026'
    assert 'CANDIDATE_ROUTE_AUTHORITY_MISSING' not in field['reason_codes']
    assert not result['claim_decision']['stp_eligible']


def test_inline_uat_labels_without_colons_and_day_first_dates():
    service = completion()
    lines = [TextLine('Patient Name JANE DOE Sex: FEMALE', 10, 10, 350, 30, .89),
             TextLine('Report Date 29/06/2026', 10, 50, 350, 70, .91)]
    layout = service.extract_page(lines, page_number=1, width=500, height=500, engine='tesseract_psm_11')
    assert [c.value for c in layout.candidates['patient_name']] == ['JANE DOE']
    assert [c.value for c in layout.candidates['report_date']] == ['29/06/2026']


def test_mer_longer_name_label_does_not_contaminate_value():
    service=completion()
    line=TextLine('Full Name of Life Assured JANE DOE',10,10,400,35,.9)
    layout=service.extract_page([line],page_number=1,width=500,height=500,engine='tesseract_psm_11')
    assert [item.value for item in layout.candidates['patient_name']]==['JANE DOE']
