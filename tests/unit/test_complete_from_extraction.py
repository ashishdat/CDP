import json
from hashlib import sha256
import pytest
from scripts.complete_from_extraction import decide, run, evidence_from_decision


def extraction():
    return {'type':'ExtractionResult','status':'ASSEMBLED',
            'document':{'document_id':'synthetic-claim'},'page':{'page_number':1},
            'field_results':[{'field_name':'patient_last','ocr':{'candidates':[]},
                'ranked_candidate':None,'alternatives':[],'candidate_validations':[],
                'validation':None,'normalized_value':None,'status':'NO_VALUE'}],
            'errors':[],'warnings':[],'telemetry':{}}


def test_existing_rules_require_review_and_missing_fields():
    result=decide(extraction(),'CMS1500')
    assert result['claim_status']=='FIELD_REVIEW_REQUIRED'
    assert result['review_required'] is True
    assert result['missing_fields']
    assert 'patient_last' in result['missing_observed_fields']
    assert result['claim_decision']['stp_eligible'] is False
    assert result['claim_decision']['runtime_profile_id']!='UNBOUND'


def test_saved_decision_consumed_and_source_preserved(tmp_path):
    source=tmp_path/'ExtractionResult.json'
    source.write_text(json.dumps(extraction()))
    original=source.read_bytes()
    output=tmp_path/'result'
    final=run(source,output,'CMS1500')
    saved=output/'DecisionResult.json'
    assert final['review_required'] is True
    assert final['field_results']==extraction()['field_results']
    assert final['evidence']['decision_sha256']==sha256(saved.read_bytes()).hexdigest()
    assert evidence_from_decision(saved)==final
    assert source.read_bytes()==original
    assert json.loads((output/'completion_telemetry.json').read_text())['input_unchanged']


def test_failed_decision_never_produces_final(tmp_path):
    source=tmp_path/'input.json'
    source.write_text(json.dumps({'type':'ExtractionResult','status':'FAILED'}))
    with pytest.raises(ValueError):run(source,tmp_path/'out','CMS1500')
    assert not (tmp_path/'out/FinalClaim.json').exists()
    events=json.loads((tmp_path/'out/completion_telemetry.json').read_text())['events']
    assert len(events)==1 and events[0]['stage']=='decision' and events[0]['status']=='FAILED'


def test_duplicates_rejected():
    value=extraction();value['field_results']*=2
    with pytest.raises(ValueError,match='unique'):decide(value,'CMS1500')


def test_evidence_rejects_wrong_document(tmp_path):
    source=tmp_path/'input.json';source.write_text(json.dumps(extraction()))
    run(source,tmp_path/'out','CMS1500')
    path=tmp_path/'out/DecisionResult.json';value=json.loads(path.read_text())
    value['document']['document_id']='different';path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='identity'):evidence_from_decision(path)
