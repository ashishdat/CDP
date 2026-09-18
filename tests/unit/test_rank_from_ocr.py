import hashlib
import json

import pytest

from packages.candidate_ranking import CandidateRankingService
from packages.extraction_recovery.contracts import CandidateObservation
from scripts.rank_from_ocr import rank_saved


def source(tmp_path):
    g=tmp_path/'geometry.json'
    g.write_text(json.dumps({'status':'SUCCESS','fields':[{'field':'test','result':{'aligned_roi':{'x0': 1,'y0': 2,'x1': 3,'y1': 4}}},{'field':'empty','result':{'aligned_roi':{'x0': 1,'y0': 2,'x1': 3,'y1': 4}}}]}))
    p=tmp_path/'ocr.json'
    p.write_text(json.dumps({'status':'COMPLETED','document_id':'synthetic','page_number':1,'geometry_reference':str(g),'geometry_sha256':hashlib.sha256(g.read_bytes()).hexdigest(),'fields':[{'field':'test','canonical_region':[1,2,3,4],'candidates':[{'raw_value':' original ','engine':'tesseract','preprocessing_variant':'recorded','raw_confidence':c} for c in [.5,.8]]},{'field':'empty','canonical_region':[1,2,3,4],'candidates':[]}]}))
    return p


def test_existing_ranking_and_telemetry(tmp_path):
    p=source(tmp_path);before=p.read_bytes()
    report,telemetry=rank_saved(p,tmp_path/'out')
    event=telemetry['events'][0]
    expected=CandidateRankingService().rank([CandidateObservation.model_validate(x) for x in event['inputs']])
    assert event['result']==expected.model_dump(mode='json')
    assert report['ranked_candidates'][0]['candidate_id']=='test:1'
    assert report['ranked_candidates'][0]['alternatives']==['test:0']
    assert len(report['empty_fields'])==1
    assert all(r['ocr_candidate']['raw_value']==' original ' for r in report['ranked_candidates'])
    assert p.read_bytes()==before
    for row in report['ranked_candidates']:
        index=int(row['telemetry_reference'].rsplit('/',1)[1])
        assert telemetry['events'][index]['field_id']==row['field_id']
    assert not telemetry['validators_called']


def test_bad_geometry_hash_stops(tmp_path):
    p=source(tmp_path);d=json.loads(p.read_text());d['geometry_sha256']='wrong';p.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='hash mismatch'):rank_saved(p,tmp_path/'out')
