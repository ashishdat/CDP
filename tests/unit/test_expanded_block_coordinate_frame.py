from PIL import Image

from evaluation.generate_expanded_block_candidates import (
    _address_candidates,
    _name_candidates,
)


def token(text, x0, y0, x1, y1):
    return {
        "text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "confidence": 0.9,
    }


def test_cms_name_block_uses_reference_form_box_2(tmp_path):
    rows = _name_candidates(
        "doc", 1, Image.new("RGB", (1712, 2214), "white"),
        [token("LEHRMAN, MATHEW", 100, 45, 400, 75)], tmp_path,
    )
    values = {(row["field_name"], row["value"]) for row in rows}
    assert ("patient_last", "LEHRMAN") in values
    assert ("patient_first", "MATHEW") in values
    assert all(row["source_bbox"]["y0"] == 320 for row in rows)


def test_cms_insured_address_uses_reference_form_box_7(tmp_path):
    rows = _address_candidates(
        "doc", 1, Image.new("RGB", (1712, 2214), "white"),
        [
            token("14390 N 99TH ST", 1050, 105, 1350, 135),
            token("SCOTTSDALE", 1050, 175, 1300, 200),
            token("AZ", 1520, 175, 1570, 200),
            token("85260", 1050, 225, 1180, 250),
        ],
        tmp_path,
    )
    values = {row["field_name"]: row["value"] for row in rows}
    assert values == {
        "insured_addr1": "14390 N 99TH ST",
        "insured_city": "SCOTTSDALE",
        "insured_state": "AZ",
        "insured_zip": "85260",
    }
    assert all(row["source_bbox"]["y0"] == 385 for row in rows)
