from PIL import Image
from packages.geometry_authority import monetary_geometry as monetary


def test_canonical_tesseract_glyphs_keep_reader_identity(monkeypatch):
    image = Image.new("L", (200, 40), 255)
    glyphs = [monetary.GlyphBox(c, x, 5, x+8, 25)
              for c, x in zip("4972", [10, 25, 130, 150])]
    monkeypatch.setattr(monetary, "_tess_digit_glyphs", lambda _: glyphs)
    monkeypatch.setattr(monetary, "_rapid_tokens", lambda _: [])
    read = monetary.read_monetary_crop(image, crop_bbox=(1000, 100, 1200, 140),
                                     image_size=(1700, 2200), cents_x=1100, units_x=1500)
    assert read.geometry_candidate == "49.72"
    assert read.reader_engine == "tesseract_digits"
    assert read.to_dict()["reader_engine"] == "tesseract_digits"


def test_rapid_token_read_keeps_rapid_identity(monkeypatch):
    image = Image.new("L", (200, 40), 255)
    monkeypatch.setattr(monetary, "_tess_digit_glyphs", lambda _: [])
    monkeypatch.setattr(monetary, "_rapid_tokens", lambda _: [
        monetary.TextToken("49.72", 10, 5, 80, 25)])
    read = monetary.read_monetary_crop(image, crop_bbox=(1000, 100, 1200, 140),
                                     image_size=(1700, 2200), cents_x=1100, units_x=1500)
    assert read.geometry_candidate == "49.72"
    assert read.reader_engine == "rapidocr"
