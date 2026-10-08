from PIL import Image
from packages.extraction_recovery.localized_dob_reader import read_localized_dob

def record():
    return {'qualification':{'qualified':True},'context_bbox':[600,380,950,520],
            'di':{'words':[{'content':t,'polygon':[x,y,x+w,y,x+w,y+24,x,y+24]} for t,x,y,w in [('04',92,53,28),('22',135,53,32),('1994',185,52,59)]]}}

def test_positions_are_not_values_or_reader_hints():
    values=iter([('04',.95),('22',.52),('1994',.94)])
    calls=[]
    def reader(crop,config):
        calls.append(config)
        return next(values)
    candidate,attempts=read_localized_dob(Image.new('L',(1712,2216),255),record(),[672,420,883,465],reader)
    assert candidate['value']=='04/22/1994'
    assert candidate['raw_confidence']==.52 and candidate['calibrated_confidence'] is None
    assert candidate['engine']=='tesseract' and not candidate['prior_hints_supplied']
    assert calls==['--psm 7']*3
    assert attempts[2]['input_bbox'][0]==783  # Includes year digit left of nominal x798.

def test_caption_digit_and_outside_field_never_become_date():
    def reader(crop,config):return 'MM 04',.99
    assert read_localized_dob(Image.new('L',(1712,2216)),record(),[672,420,883,465],reader)[0] is None
    r=record();r['di']['words'][2]['polygon'][5]=99
    assert read_localized_dob(Image.new('L',(1712,2216)),r,[672,420,883,465],reader)==(None,[])

def test_agreement_not_enough_without_qualified_geometry():
    r=record();r['qualification']['qualified']=False
    def reader(*args):raise AssertionError('Must not read unqualified crop')
    assert read_localized_dob(Image.new('L',(1712,2216)),r,[672,420,883,465],reader)==(None,[])
