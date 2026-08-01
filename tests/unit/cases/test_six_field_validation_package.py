from evaluation.build_six_field_validation_package import REFERENCE_FIELDS, _projection_record


def test_validation_package_contains_exact_six_reference_fields() -> None:
    assert len(REFERENCE_FIELDS) == 6
    assert len(set(REFERENCE_FIELDS)) == 6


def test_christopher_projection_is_specification_bounded() -> None:
    result = _projection_record()
    assert result["source_value"] == "CHRISTOPHER"
    assert result["output_value"] == "CHRISTOPH"
    assert not result["visible_ocr_candidate"]
