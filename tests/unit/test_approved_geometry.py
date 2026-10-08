import hashlib,json
import pytest
from packages.extraction_recovery.approved_geometry import frame_hash,load_approved_geometry,acquire_approved_geometry
from PIL import Image

def test_source_page_frame_and_hash_bind_override(tmp_path):
    g={'page_number':1,'template_id':'ub04','source_to_geometry_transform':[[1,0,0],[0,1,0],[0,0,1]]}
    entry={'source_sha256':'a'*64,'page_number':1,'field':'patient_name','bbox':[2,2,8,8],'frame_sha256':frame_hash(g),'validation_id':'approved'}
    p=tmp_path/'manifest.json';p.write_text(json.dumps({'schema_version':'approved-source-geometry-v1','operator_validated':True,'entries':[entry]}));sha=hashlib.sha256(p.read_bytes()).hexdigest()
    assert load_approved_geometry(p,sha,'a'*64,g,(10,10))['patient_name']=={**entry,'runtime_binding_verified':True}
    assert load_approved_geometry(p,sha,'b'*64,g,(10,10))=={}
    assert load_approved_geometry(p,sha,'a'*64,{**g,'page_number':2},(10,10))=={}
    with pytest.raises(ValueError):load_approved_geometry(p,sha,'a'*64,{**g,'template_id':'cms1500'},(10,10))
    with pytest.raises(ValueError):load_approved_geometry(p,'wrong','a'*64,g,(10,10))

def test_new_observation_keeps_original_rival_and_alignment_gate():
    row={'field':'patient_name','candidates':[{'engine':'paddleocr','value':'OLD'}],'attempts':[], 'local_alignment':{'accepted':False}}
    def reader(name,box):return [{'engine':'rapidocr','value':'NEW'}],[{'engine':'rapidocr','reason':'OBSERVED'}],'OBSERVED'
    result=acquire_approved_geometry([row],Image.new('L',(10,10)),{'patient_name':{'bbox':[2,2,8,8],'validation_id':'approved'}},reader)[0]
    assert len(result['candidates'])==2 and len(row['candidates'])==1
    assert result['local_alignment']['accepted'] is False
