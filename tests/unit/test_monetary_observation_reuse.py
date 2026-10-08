from PIL import Image
from packages.geometry_authority import monetary_geometry as m

def test_same_crop_uses_one_real_rapid_read(monkeypatch):
    calls=[]
    def read(image):calls.append(image.size);return [m.TextToken('400.00',10,10,80,30)]
    monkeypatch.setattr(m,'_rapid_tokens',read)
    monkeypatch.setattr(m,'_tess_digit_glyphs',lambda image:[])
    result=m.read_monetary_crop(Image.new('L',(200,50),255),crop_bbox=(1045,1825,1245,1875),image_size=(1712,2214),cents_x=1182,units_x=1248)
    assert len(calls)==1
    assert result.geometry_candidate=='400.00'
    assert result.reader_engine=='rapidocr'
