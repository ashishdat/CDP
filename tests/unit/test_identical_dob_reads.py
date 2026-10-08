from PIL import Image
from scripts import ocr_from_geometry as module

def test_normalized_identical_empty_crops_are_not_rerun_or_new_votes(monkeypatch):
    calls=[]
    def read(*args):
        calls.append(args)
        return [],[{'engine':'tesseract','observation':{'parts':{'MM':'09','DD':'29','YY':''}}}],'DOB_CELLS_EMPTY'
    monkeypatch.setattr(module,'_recognize_dob_cells_for_engine_uncached',read)
    image=Image.new('L',(1712,2214),255);cell=(672,420,883,465)
    module._recognize_dob_cells_for_engine(image,cell,None,('tesseract',),cell)
    _,trace,_=module._recognize_dob_cells_for_engine(image,(672,430,883,455),None,('tesseract',),cell)
    assert len(calls)==1
    assert trace[0]['new_reader_observation'] is False
    assert 'parts' not in trace[0]

def test_new_pixels_are_not_suppressed_by_cache(monkeypatch):
    calls=[]
    def read(*args):
        calls.append(args);return [],[{'engine':'tesseract','observation':{'parts':{'MM':'09'}}}],'DOB_CELLS_EMPTY'
    monkeypatch.setattr(module,'_recognize_dob_cells_for_engine_uncached',read)
    image=Image.new('L',(1712,2214),255);cell=(672,420,883,465)
    module._recognize_dob_cells_for_engine(image,cell,None,('tesseract',),cell)
    image.putpixel((700,440),0)
    module._recognize_dob_cells_for_engine(image,cell,None,('tesseract',),cell)
    assert len(calls)==2
