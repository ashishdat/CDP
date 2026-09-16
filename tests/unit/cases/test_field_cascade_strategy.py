"""Field-cascade OCR strategy unit tests."""

from __future__ import annotations

from packages.extraction_recovery.field_cascade import (
    FieldCascade,
    charge_column_windows,
    crop_variants,
    load_route_engines,
    semantic_accept,
)


def test_route_engines_prefer_governed_primary_then_confirmation():
    engines = load_route_engines("patient_dob")
    assert engines[0] == "paddleocr"
    assert engines[1] == "rapidocr"


def test_semantic_accept_date_currency_name_id():
    assert semantic_accept("patient_dob", "10/29/1983")[0] is True
    assert semantic_accept("patient_dob", "MM L 29")[0] is False
    assert semantic_accept("total_charge", "2084.80")[0] is True
    assert semantic_accept("total_charge", "-2084.80")[0] is False
    assert semantic_accept("total_charge", "1.00")[0] is False
    assert semantic_accept("patient_name", "DOLIET MARGARET M")[0] is True
    assert semantic_accept("insured_id_number", "OSC75491075")[0] is True


def test_dob_crop_ladder_includes_digit_band():
    variants = crop_variants(
        "patient_dob",
        (672, 424, 871, 457),
        {"x0": 667, "y0": 402, "x1": 886, "y1": 459},
        (1700, 2200),
    )
    ids = [v.variant_id for v in variants]
    assert ids[0] == "primary"
    assert "dob_digit_band" in ids


def test_charge_column_windows_shift_right_of_pointer_bleed():
    windows = charge_column_windows(940, 1100)
    assert windows[0] == ("charges_primary", 940, 1100)
    assert any(x0 >= 1000 for _, x0, _ in windows[1:])


def test_cascade_prefers_shaped_confirmation_over_primary_bleed():
    calls = []

    def recognize_fn(field_name, bbox, field_type, engines):
        calls.append(bbox)
        # Dual-engine candidates: primary bleed + confirmation date.
        return (
            [
                {
                    "value": "MM L 29 1 ds 3",
                    "raw_value": "MM\nL\n29",
                    "engine": "paddleocr",
                },
                {
                    "value": "10/29/1983",
                    "raw_value": "10/29/1983",
                    "engine": "rapidocr",
                },
            ],
            [
                {"engine": "paddleocr", "reason": "OBSERVED"},
                {"engine": "rapidocr", "reason": "OBSERVED"},
            ],
            "POLICY_SATISFIED",
        )

    result = FieldCascade().recognize(
        field_name="patient_dob",
        primary_bbox=(672, 424, 871, 457),
        cell={"x0": 667, "y0": 402, "x1": 886, "y1": 459},
        image_size=(1700, 2200),
        recognize_fn=recognize_fn,
    )
    assert result.accepted is True
    assert result.candidates[0]["value"] == "10/29/1983"
    assert result.accept_reason.endswith("DATE_SHAPED")
    assert len(calls) == 1


def test_cascade_stops_on_first_semantic_accept():
    calls = []

    def recognize_fn(field_name, bbox, field_type, engines):
        calls.append(bbox)
        y0 = bbox[1]
        if y0 >= 430:
            value = "10/29/1983"
            raw = "29\n1983\n10"
        else:
            value = "MM L 29 1 ds 3"
            raw = "MM\nL\n29\n1\nds\n3"
        candidate = {"value": value, "raw_value": raw, "engine": engines[0]}
        return [candidate], [{"engine": engines[0], "reason": "OBSERVED"}], "POLICY_SATISFIED"

    result = FieldCascade().recognize(
        field_name="patient_dob",
        primary_bbox=(672, 424, 871, 457),
        cell={"x0": 667, "y0": 402, "x1": 886, "y1": 459},
        image_size=(1700, 2200),
        recognize_fn=recognize_fn,
    )
    assert result.accepted is True
    assert result.candidates[0]["value"] == "10/29/1983"
    assert len(calls) >= 1
