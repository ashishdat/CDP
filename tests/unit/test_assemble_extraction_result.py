import hashlib
import json

import pytest

from scripts.assemble_extraction_result import assemble


def fixture(tmp_path):
    def save(name,data):
        p=tmp_path/name;p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(data));return p
    def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    box={'x0': 1,'y0': 2,'x1': 3,'y1': 4}
    g=save('g.json',{'status':'SUCCESS','page_number':1,'fields':[{'field':n,'result':{'aligned_roi':box}} for n in ['a','b']]})
    original={'raw_value':' raw '}
    o=save('ocr/ocr.json',{'status':'COMPLETED','document_id':'doc','page_number':1,'coordinate_frame':'rectified_template_pixels','geometry_reference':str(g),'geometry_sha256':digest(g),'fields':[{'field':'a','canonical_region':[1,2,3,4],'candidates':[original]},{'field':'b','canonical_region':[1,2,3,4],'candidates':[]}]})
    c={'field_id':'a','candidate_id':'a:0','is_winner':True,'winner':'a:0','confidence':.8,'ocr_candidate':original,'telemetry_reference':'ranking_telemetry.json#/events/0'}
    r=save('rank/rank.json',{'status':'SUCCESS','document_id':'doc','page_number':1,'source_sha256':digest(o),'ranked_candidates':[c]})
    v=save('val/val.json',{'status':'COMPLETED','document_id':'doc','source_sha256':digest(r),'results':[{'field_id':'a','candidate_id':'a:0','status':'VALID','reason':['existing check'],'normalized_value':'raw','telemetry_reference':'validator_telemetry.json#/events/0'}]})
    save('ocr/ocr_telemetry.json',{'fields_completed':2})
    save('rank/ranking_telemetry.json',{'events':[{'field_id':'a'}]})
    save('val/validator_telemetry.json',{'events':[{'field_id':'a','candidate_id':'a:0'}]})
    return o,r,v


def test_complete_join_preserves_values_and_empty_fields(tmp_path):
    paths=fixture(tmp_path);before=[p.read_bytes() for p in paths]
    r=assemble(*paths,tmp_path/'out')
    assert r['statistics']['fields']==2
    assert r['field_results'][0]['ocr']['candidates'][0]['raw_value']==' raw '
    assert r['field_results'][0]['normalized_value']=='raw'
    assert r['field_results'][1]['status']=='NO_VALUE'
    assert r['field_results'][1]['validation'] is None
    assert not r['decision_called'] and not r['evidence_called']
    assert [p.read_bytes() for p in paths]==before
    assert json.loads((tmp_path/'out/ExtractionResult.json').read_text())==r


def test_modified_input_rejected(tmp_path):
    paths=fixture(tmp_path);paths[0].write_text(paths[0].read_text()+' ')
    with pytest.raises(ValueError,match='hash chain'):assemble(*paths,tmp_path/'out')


def test_wrong_telemetry_identity_rejected(tmp_path):
    paths=fixture(tmp_path);(tmp_path/'val/validator_telemetry.json').write_text(json.dumps({'events':[{'field_id':'wrong','candidate_id':'a:0'}]}))
    with pytest.raises(ValueError,match='Telemetry field'):assemble(*paths,tmp_path/'out')
