import pytest
from packages.extraction_recovery import dob_recovery_contract as m

def test_geometry_precedes_read_and_retains_conflict_trace():
    result=m.plan_recovery([{'engine':'tesseract','value':'01/19/2026'},{'engine':'azure_di','value':'01/19/2020'}],[],geometry_qualified=False)
    assert result['state']=='NEEDS_GEOMETRY'
    assert 'COMPLETE_DATE_DISAGREEMENT' in result['blocking_mechanisms']

def test_wrong2026_is_a_rival_not_recovery_of2020():
    result=m.plan_recovery([{'engine':'tesseract','value':'01/19/2026'},{'engine':'azure_di','value':'01/19/2020'}],[],geometry_qualified=True)
    assert result['state']=='FULL_DATE_CONFLICT' and result['acceptance_authority']=='NONE'

def test_partial_component_is_distinct_from_missing_read():
    result=m.plan_recovery([{'engine':'paddleocr','value':'11/27/1969'}],[{'engine':'tesseract','observation':{'parts':{'YY':'1949'}}}],geometry_qualified=True)
    assert result['state']=='PARTIAL_COMPONENT_CONFLICT'
    assert m.plan_recovery([],[],geometry_qualified=True)['state']=='NEEDS_READ'

def test_hint_does_not_supply_confirmation_and_budget_is_explicit():
    candidates=[{'engine':'claude','value':'11/27/1969'},{'engine':'paddleocr','value':'11/27/1969','prior_hints_supplied':True}]
    assert m.plan_recovery(candidates,[],geometry_qualified=True)['state']=='NEEDS_CONFIRMATION'
    assert m.plan_recovery(candidates,[],geometry_qualified=True,remaining_reads=0)['state']=='BUDGET_EXHAUSTED'

def test_ready_never_grants_acceptance():
    result=m.plan_recovery([{'engine':'paddleocr','value':'11/27/1969'},{'engine':'rapidocr','value':'11/27/1969'}],[],geometry_qualified=True)
    assert result['state']=='READY_FOR_EXISTING_POLICY' and result['readiness_is_not_policy_acceptance']

def test_identical_source_pixel_reader_reuses_observation():
    ledger=m.ObservationLedger();key=m.ObservationKey('a'*64,1,'patient_dob','b'*64,(0,0,10,10),'c'*64,'tesseract@5.4','psm7')
    first,new=ledger.observe(key,lambda:('2020',.84));assert new
    second,new=ledger.observe(key,lambda:pytest.fail('Duplicate reader call'))
    assert not new and second==first and second.calibrated_confidence is None
    other=m.ObservationKey('d'*64,1,'patient_dob','b'*64,(0,0,10,10),'c'*64,'tesseract@5.4','psm7')
    assert ledger.observe(other,lambda:('2026',.8))[1]

def test_invalid_confidence_and_failed_reads_not_cached():
    ledger=m.ObservationLedger();key=m.ObservationKey('a'*64,1,'patient_dob','b'*64,(0,0,10,10),'c'*64,'tesseract@5.4','psm7')
    with pytest.raises(ValueError):ledger.observe(key,lambda:('2020',float('nan')))
    assert ledger.observe(key,lambda:('2020',.84))[1]

def test_reader_disagreement_does_not_invalidate_geometry():
    record={'qualification':{'qualified':False,'reason':'PROVIDER_AGREEMENT_NOT_ESTABLISHED'},'context_bbox':[0,0,100,40],
        'di':{'words':[{'content':text,'polygon':[x,10,x+15,10,x+15,30,x,30]} for x,text in [(5,'01'),(30,'19'),(55,'2020')]]}}
    assert m.qualify_value_row(record,[0,0,100,40])['qualified']

def test_staged_reader_uses_geometry_without_date_hints_and_reuses_pixels():
    from PIL import Image
    from packages.extraction_recovery import localized_dob_reader as reader_module
    record={'source_sha256':'a'*64,'page_number':1,'frame_sha256':'b'*64,'qualification':{'qualified':False},'context_bbox':[0,0,100,40],
        'di':{'words':[{'content':text,'polygon':[x,10,x+15,10,x+15,30,x,30]} for x,text in [(5,'04'),(30,'22'),(55,'1994')]]}}
    values=iter([('04',.95),('22',.52),('1994',.94)]);calls=[]
    def blind_read(crop,config):calls.append(config);return next(values)
    image=Image.new('L',(100,40),255)
    first,attempts=reader_module.read_localized_dob(image,record,[0,0,100,40],blind_read)
    second,reused=reader_module.read_localized_dob(image,record,[0,0,100,40],blind_read)
    assert first['value']==second['value']=='04/22/1994' and len(calls)==3
    assert not any(a.get('new_reader_observation') for a in reused if a.get('dob_cell'))
    assert not m.dob_reads_confirmed([first,second])
