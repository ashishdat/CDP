import copy

from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance
from workers.unstructured_extraction.observed_type import resolve_observed_type


def evidence():
    return {'records':[{'status':'SUCCESS','provider':'azure_claude','job_id':'photo',
        'source_image':'/sample/page_001.png','crop_fraction':[.02,.02,.98,.98],
        'fields':[{'field_name':'content_kind','value':'portrait_photo',
                   'confidence':.97,'insufficient_evidence':False}]}],
        'assets':[{'path':'/sample/page_001.png'}],'sources':[(1,[])],
        'candidates':{},'policy':ExtractionAcceptance().config,'successful_di_pages':[1]}


def test_observed_portrait_overrides_filename_with_complete_evidence():
    result=resolve_observed_type('PAN',**evidence())
    assert result['declared_type']=='PAN'
    assert result['effective_type']=='PERSON_PHOTO'
    assert result['evidence_references']==['photo']


def test_empty_ocr_without_visual_classification_never_changes_type():
    data=evidence();data['records']=[]
    assert not resolve_observed_type('PAN',**data)['changed']


def test_failed_di_or_small_crop_cannot_downgrade_identity_requirements():
    data=evidence();data['successful_di_pages']=[]
    assert not resolve_observed_type('PAN',**data)['changed']
    data=evidence();data['records'][0]['crop_fraction']=[0,0,.4,.4]
    assert not resolve_observed_type('PAN',**data)['changed']


def test_identity_evidence_or_conflicting_classification_prevents_override():
    data=evidence();data['candidates']={'identity_number':[{'value':'ABCDE1234F'}]}
    assert not resolve_observed_type('PAN',**data)['changed']
    data=evidence();other=copy.deepcopy(data['records'][0])
    other['fields'][0]['value']='identity_card';data['records'].append(other)
    assert not resolve_observed_type('PAN',**data)['changed']


def test_low_confidence_or_incomplete_page_coverage_prevents_override():
    data=evidence();data['records'][0]['fields'][0]['confidence']=.8
    assert not resolve_observed_type('PAN',**data)['changed']
    data=evidence();data['assets'].append({'path':'/sample/page_002.png'})
    data['sources'].append((2,[]));data['successful_di_pages'].append(2)
    assert not resolve_observed_type('PAN',**data)['changed']
