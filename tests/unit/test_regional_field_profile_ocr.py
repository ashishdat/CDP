from PIL import Image

from packages.ocr.preprocessing import PreprocessingRegistry
from workers.page_detection.text_extraction import RapidOCRTextExtractor


def test_regional_extractor_applies_digit_preserving_profile(tmp_path):
    config = tmp_path / "prep.yaml"
    config.write_text(
        """
version: "test"
default_profile: GENERAL_TEXT
profiles:
  GENERAL_TEXT: [safe_border, grayscale]
  DIGIT_PRESERVING_V2: [safe_border, grayscale, upscale_2x]
field_rules:
  - {profile: DIGIT_PRESERVING_V2, contains: [npi]}
""",
        encoding="utf-8",
    )
    shapes = []

    def backend(array):
        shapes.append(array.shape)
        return [([[1, 1], [5, 1], [5, 4], [1, 4]], "1999999984", 0.9)], [0.01, 0.01, 0.01]

    extractor = RapidOCRTextExtractor(
        backend=backend,
        preprocessing_registry=PreprocessingRegistry.load(config),
        enable_ocr_recovery=False,
    )
    extractor.set_context(field="provider_npi", field_type="npi")
    lines = extractor.extract_region(Image.new("RGB", (40, 20), "white"), 0, 0, 40, 20)
    assert [line.text for line in lines] == ["1999999984"]
    assert extractor.last_preprocessing_profile == "DIGIT_PRESERVING_V2"
    # safe_border (+4px) then upscale_2x: 40x20 -> 96x56. Must not stack blind 3x (120x60).
    assert shapes[0][0] == 56 and shapes[0][1] == 96
    assert shapes[0][0] != 60 and shapes[0][1] != 120


def test_regional_extractor_runs_one_recovery_profile_on_empty_primary(tmp_path):
    config = tmp_path / "prep.yaml"
    config.write_text(
        """
version: "test"
default_profile: GENERAL_TEXT
profiles:
  GENERAL_TEXT: [safe_border, grayscale]
  DIGIT_PRESERVING_V2: [safe_border, grayscale]
field_rules:
  - {profile: DIGIT_PRESERVING_V2, contains: [npi]}
""",
        encoding="utf-8",
    )
    calls = {"n": 0}

    def backend(_array):
        calls["n"] += 1
        if calls["n"] == 1:
            return [], [0.01, 0.01, 0.01]
        return [([[0, 0], [4, 0], [4, 3], [0, 3]], "1999999984", 0.91)], [0.01, 0.01, 0.01]

    extractor = RapidOCRTextExtractor(
        backend=backend,
        preprocessing_registry=PreprocessingRegistry.load(config),
        enable_ocr_recovery=True,
    )
    extractor.set_context(field="billing_npi")
    lines = extractor.extract_region(Image.new("RGB", (30, 12), "white"), 0, 0, 30, 12)
    assert [line.text for line in lines] == ["1999999984"]
    assert calls["n"] == 2
    assert extractor.last_profile["ocr_recovery_profile"] == "GENERAL_TEXT"
