
import pytest

from packages.ocr.text_extraction import TextLine
from scripts.run_uat_all import SERVICE
from tests.unit.test_uat_extraction_acceptance import ASSETS, candidate, page
from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance
from workers.unstructured_extraction.uat_binding_v5 import (
    bound_candidates,
    licence_content,
    licence_date_role,
)
from workers.unstructured_extraction.uat_rotation import crop_fraction, point, transform_di
from workers.unstructured_extraction.uat_values import date_value


def layout(lines,kind='PAN'):
    return SERVICE.extract_page([TextLine(text,10,y,450,y+18,.95) for y,text in lines],
        page_number=1,width=600,height=800,engine='test',document_family=kind)


@pytest.mark.parametrize('raw',['26-Jun-2026','26 June 2026','Jun 26, 2026','June 26 2026'])
def test_month_name_dates_preserve_raw(raw):
    value=date_value(raw)
    assert value['canonical_value']=='2026-06-26'
    assert value['raw_value']==raw


def test_invalid_month_date_and_short_year_not_guessed():
    assert not date_value('31-Feb-2026')['valid_format']
    assert date_value('27/06/26')['year_ambiguous']


def test_older_pan_holder_is_first_name_not_name_nearest_dob():
    source=layout([(10,'INCOME TAX DEPARTMENT'),(50,'JANE DOE'),(80,'JOHN DOE'),
                   (110,'04/06/1968'),(140,'Permanent Account Number'),(170,'ABCDE1234F')])
    values,audit=bound_candidates('IDENTITY_PROOF',[source],{'patient_name':[candidate('JOHN DOE')]})
    assert audit[0]['holder']['value']=='JANE DOE'
    assert values['patient_name'][0]['role_conflict']
    assert values['patient_name'][-1]['value']=='JANE DOE'


def test_pan_attachment_does_not_override_medical_document_name():
    source=layout([(10,'SBI Life Insurance Company Limited'),(40,'INCOME TAX DEPARTMENT'),
                   (80,'JANE DOE'),(110,'JOHN DOE'),(140,'04/06/1968')],kind='MER')
    values,audit=bound_candidates('MER',[source],{'patient_name':[candidate('Jane Doe')]})
    assert not audit
    assert not values['patient_name'][0].get('role_conflict')


def test_pan_logo_above_issuer_is_not_a_holder_name():
    source=layout([(10,'TM'),(40,'INCOME TAX DEPARTMENT'),(80,'JANE DOE'),
                   (110,'JOHN DOE'),(140,'04/06/1968')])
    values,audit=bound_candidates('IDENTITY_PROOF',[source],{})
    assert audit[0]['holder']['value']=='JANE DOE'
    assert all(item['value']!='TM' for item in values['patient_name'])


def test_name_boundary_removes_bill_number_label():
    source=layout([(10,'CBC'),(80,'Patient Name: Jane Doe Bill No: 12345')],kind='PATH')
    values,_=bound_candidates('PATH',[source],{'patient_name':[candidate('Jane Doe Bill No')]})
    assert values['patient_name'][0]['role_conflict']
    assert any(item['value']=='Jane Doe' for item in values['patient_name'])


def test_adjacent_doctor_value_is_not_patient_name():
    source=layout([(10,'Patient Name: Jane Doe'),(50,'Doctor Name: John Brown')],kind='PATH')
    wrong={**candidate('John Brown'),'page_number':1}
    values,_=bound_candidates('PATH',[source],{'patient_name':[wrong]})
    assert values['patient_name'][0]['role_conflict']


def test_parent_address_value_is_not_holder_name():
    source=layout([(10,'Government of India'),(50,'Address: S/O JOHN DOE')],kind='AADHAAR')
    wrong={**candidate('JOHN DOE'),'page_number':1}
    values,_=bound_candidates('AADHAAR',[source],{'patient_name':[wrong]})
    assert values['patient_name'][0]['role_conflict']


def test_licence_card_evidence_and_number_binding():
    source=layout([(10,'INDIAN UNION DRIVING LICENCE'),(40,'Driving Licence No: WB18 20090023546'),
                   (80,'Name: JANE DOE'),(110,'Date of Birth: 19-12-1981'),
                   (140,'Valid Till: 16-03-2029')],kind='DRIVING_LICENSE')
    assert licence_content([source])
    values,_=bound_candidates('DRIVING_LICENSE',[source],{})
    assert values['license_number'][0]['value']=='WB18 20090023546'
    assert values['patient_name'][0]['value']=='JANE DOE'


def test_certificate_date_is_not_declaration_date():
    certificate=layout([(10,'CERTIFICATE'),(80,'Name of Doctor: Dr Other'),
                        (110,'Date: 26 June 2026 Place: Delhi')],kind='MER')
    declaration=layout([(10,'Declaration by Life Assured'),(110,'Date: 26 June 2026')],kind='MER')
    assert bound_candidates('MER',[certificate],{})[0]['examination_date'][0]['value']=='26 June 2026'
    assert 'examination_date' not in bound_candidates('MER',[declaration],{})[0]


def test_registration_date_does_not_become_report_date():
    source=layout([(10,'CBC'),(80,'Registered: 26 Jun 2026')],kind='PATH')
    assert 'report_date' not in bound_candidates('PATH',[source],{})[0]
    mapped={**candidate('26 Jun 2026'),'field_association':'LLM_VALUE_LOCATED_IN_OCR','page_number':1}
    result,_=bound_candidates('PATH',[source],{'report_date':[mapped]})
    assert result['report_date'][0]['role_conflict']


def test_medical_form_licence_checkbox_is_not_a_licence_card():
    source=layout([(10,'Medical Examination Report'),(40,'Form of Identification Produced:'),
        (80,'Driving License No. Passport Number'),(110,'Date of Birth: 04/06/1968')],kind='MER')
    assert not licence_content([source])


def test_certificate_prose_is_not_a_name_label():
    source=layout([(10,'CERTIFICATE'),(80,'examined the life to be assured and I am satisfied about the')],kind='MER')
    assert not bound_candidates('MER',[source],{})[0].get('patient_name')


def test_vertical_issue_date_is_not_bound_as_licence_expiry():
    assert licence_date_role({'bounding_box':{'x0':1500,'y0':100,'x1':1540,'y1':320}},[]) is None


def test_low_name_acceptance_requires_verified_other_document():
    service=ExtractionAcceptance()
    args={'expected_pages':1,'assets':ASSETS,'candidates':{'patient_name':[candidate('JANE DOE',.49)],
                                                         'report_date':[candidate('26/06/2026')]},
          'document_id':'case/medical','known_names':['JANE DOE']}
    ref={'document_id':'case/id','value':'JANE DOE','raw_confidence':.95,
         'source_verified':True,'evidence_reference':'page:1:holder'}
    result=service.decide('PATH',[page('CBC')],verified_name_sources=[ref],**args)
    assert result['extraction_stp_eligible']
    assert result['extracted_fields']['patient_name']['raw_confidence']==.49
    assert service.config['minimum_ocr_confidence']==.80
    for bad in [{**ref,'document_id':'case/medical'},{**ref,'source_verified':False},{**ref,'value':'JANE BROWN'}]:
        assert not service.decide('PATH',[page('CBC')],verified_name_sources=[bad],**args)['extraction_stp_eligible']


def test_unsupported_handwritten_spelling_variant_stays_in_review():
    ref={'document_id':'case/id','value':'SIVAKUMAR','raw_confidence':.95,
         'source_verified':True,'evidence_reference':'page:1:holder'}
    value={**candidate('SIVAKUMOR',0),'field_association':'HANDWRITTEN_CROP_CASE_NAME_MATCH',
           'source_reading_ambiguous':True,'ocr_confidence_available':False}
    result=ExtractionAcceptance().decide('PATH',[page('CBC')],expected_pages=1,assets=ASSETS,
        candidates={'patient_name':[value],'report_date':[candidate('26/06/2026')]},
        document_id='case/medical',verified_name_sources=[ref],known_names=['SIVAKUMAR'])
    assert not result['extraction_stp_eligible']


def test_rotation_transforms_crop_and_polygons_consistently():
    assert point(10,20,100,200,90)==(20,90)
    assert crop_fraction([0,0,.5,.5],100,200,90)==[0,.5,.5,1]
    source={'payload':{'analyzeResult':{'pages':[{'width':100,'height':200,'angle':90,
        'words':[{'content':'NAME','polygon':[10,20,30,20,30,40,10,40]}]}]}}}
    transformed=transform_di(source,{'width':100,'height':200},90)
    dest=transformed['payload']['analyzeResult']['pages'][0]
    assert dest['width']==200 and dest['height']==100
    assert dest['words'][0]['polygon'][:2]==[20,90]
    assert source['payload']['analyzeResult']['pages'][0]['angle']==90
