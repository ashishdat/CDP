import json
from uuid import uuid4

import pytest

from packages.validation_rules.engine import ValidationEngine
from packages.validation_rules.thresholds import ThresholdRegistry
from scripts.validate_from_ranked import run, validate_candidate


def row(raw,confidence=1.,field='patient_last'):
    return {'candidate_id':field+':0','field_id':field,'ranking_reason':[],
            'ocr_candidate':{'raw_value':raw,'raw_confidence':confidence}}


@pytest.mark.parametrize('raw,confidence,field,kind,status',[
    ('  Smith  ',1.,'patient_last','text','VALID'),
    ('Smith',.1,'patient_last','text','SUSPICIOUS'),
    ('',1.,'patient_last','text','NO_VALUE'),
    ('bad',1.,'provider_npi','npi','INVALID'),
])
def test_existing_field_rules(raw,confidence,field,kind,status):
    candidate=row(raw,confidence,field)
    before=json.dumps(candidate)
    result,checks=validate_candidate(candidate,kind,ValidationEngine(ThresholdRegistry.load_from_directory()),uuid4())
    assert result['status']==status
    assert json.dumps(candidate)==before
    if status=='SUSPICIOUS':assert checks[0]['rule_name']=='confidence_threshold'


def test_saved_input_integration_and_telemetry(tmp_path):
    p=tmp_path/'ranked.json'
    p.write_text(json.dumps({'status':'SUCCESS','document_id':'synthetic','ranked_candidates':[row('Smith')]}))
    before=p.read_bytes()
    result=run(p,tmp_path/'out','cms1500','02-12')
    telemetry=json.loads((tmp_path/'out/validator_telemetry.json').read_text())
    assert result['status']=='COMPLETED'
    assert len(result['results'])==len(telemetry['events'])==1
    assert result['results'][0]['telemetry_reference']=='validator_telemetry.json#/events/0'
    assert not telemetry['decision_called'] and not telemetry['evidence_called']
    assert p.read_bytes()==before
