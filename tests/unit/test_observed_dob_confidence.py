import sys
from types import SimpleNamespace
from PIL import Image
from scripts.ocr_from_geometry import _tesseract_text_with_confidence


def test_dob_confidence_is_from_same_observed_tokens(monkeypatch):
    native=SimpleNamespace(Output=SimpleNamespace(DICT="dict"),image_to_data=lambda *a,**k:{
        "text":["", "09", "29", "1967"],"conf":["-1","91","89","72"]})
    monkeypatch.setitem(sys.modules,"pytesseract",native)
    text,confidence=_tesseract_text_with_confidence(Image.new("L",(20,20)),"--psm 7")
    assert text == "09 29 1967"
    assert confidence == .72


def test_missing_native_confidence_is_not_invented(monkeypatch):
    native=SimpleNamespace(Output=SimpleNamespace(DICT="dict"),image_to_data=lambda *a,**k:{
        "text":["09", "29", "1967"],"conf":["-1","nan","-1"]})
    monkeypatch.setitem(sys.modules,"pytesseract",native)
    assert _tesseract_text_with_confidence(Image.new("L",(20,20)),"")[1] == 0
