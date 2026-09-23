"""Strict cloud stop ladder: locals settled → skip cloud; one cloud only."""

from __future__ import annotations

import pytest

from packages.extraction_recovery.cloud_stop_ladder import (
    FIELD_AUTHORITY_CODES,
    charge_locals_settled,
    dob_locals_settled,
    field_has_authority,
    id_locals_settled,
    name_locals_settled,
    one_cloud_already_shaped,
    should_skip_all_cloud,
    should_skip_second_cloud,
)


@pytest.fixture(autouse=True)
def _ladder_on(monkeypatch):
    monkeypatch.setenv("CDP_CLOUD_STOP_LADDER", "1")


def test_charge_locals_settled_two_families_same_non_bleed():
    cands = [
        {"engine": "rapidocr", "value": "660.00"},
        {"engine": "paddleocr", "value": "660.00"},
        {"engine": "azure_gpt4o_crop", "value": "50.00"},
    ]
    assert charge_locals_settled(cands)
    row = {"field": "total_charge", "candidates": cands}
    assert should_skip_all_cloud("total_charge", row)


def test_charge_locals_not_settled_single_family():
    assert not charge_locals_settled(
        [{"engine": "rapidocr", "value": "660.00"}]
    )


def test_charge_locals_settled_ignores_units_bleed_cents():
    # 342.01 is units-bleed; agreeing bleed alone does not settle Box 28.
    assert not charge_locals_settled(
        [
            {"engine": "rapidocr", "value": "342.01"},
            {"engine": "paddleocr", "value": "342.01"},
        ]
    )
    # Non-bleed agreement still settles even when bleed rivals exist.
    assert charge_locals_settled(
        [
            {"engine": "rapidocr", "value": "660.00"},
            {"engine": "paddleocr", "value": "660.00"},
            {"engine": "tesseract", "value": "342.01"},
        ]
    )


def test_dob_locals_settled_display_shaped():
    cands = [{"engine": "rapidocr", "value": "03/15/1987"}]
    assert dob_locals_settled(cands)
    assert should_skip_all_cloud(
        "patient_dob", {"field": "patient_dob", "candidates": cands}
    )


def test_dob_locals_settled_two_families_same_ymd():
    cands = [
        {"engine": "rapidocr", "value": "03/15/1987"},
        {"engine": "paddleocr", "value": "1987-03-15"},
    ]
    assert dob_locals_settled(cands)


def test_id_locals_settled_two_shaped_families():
    cands = [
        {"engine": "rapidocr", "value": "W123456789"},
        {"engine": "paddleocr", "value": "W123456789"},
    ]
    assert id_locals_settled(cands)
    assert should_skip_all_cloud(
        "insured_id_number",
        {"field": "insured_id_number", "candidates": cands},
    )


def test_name_locals_settled_soft_equivalent_families():
    # Punctuation-only difference still normalizes to the same token.
    cands = [
        {"engine": "rapidocr", "value": "SMITH, JOHN"},
        {"engine": "paddleocr", "value": "SMITH JOHN"},
    ]
    assert name_locals_settled(cands)
    assert should_skip_all_cloud(
        "patient_name", {"field": "patient_name", "candidates": cands}
    )


def test_name_locals_not_settled_on_initial_soup():
    # Soft-eq-ish garbage must not skip cloud (MISSING_E2 / conflict margin).
    cands = [
        {"engine": "rapidocr", "value": "ACOSTA, BRIDGITA"},
        {"engine": "paddleocr", "value": "ACOS'TA, BRIDGITA"},
    ]
    # Apostrophe may normalize equal — if so still settled; force distinct.
    cands2 = [
        {"engine": "rapidocr", "value": "crmauiani . Aiay . M"},
        {"engine": "paddleocr", "value": "CRAMIGNANI, AJAY M"},
    ]
    assert not name_locals_settled(cands2)


def test_charge_locals_not_settled_when_zero_lines():
    cands = [
        {"engine": "rapidocr", "value": "90.00"},
        {"engine": "paddleocr", "value": "90.00"},
    ]
    assert charge_locals_settled(cands)  # legacy: no line context
    assert not charge_locals_settled(cands, observed_line_charges=[])
    assert should_skip_all_cloud(
        "total_charge",
        {"field": "total_charge", "candidates": cands},
        observed_line_charges=[],
    ) is False


def test_charge_locals_not_settled_on_line_place_shift():
    cands = [
        {"engine": "rapidocr", "value": "251.00"},
        {"engine": "paddleocr", "value": "251.00"},
    ]
    assert not charge_locals_settled(
        cands, observed_line_charges=["2.51"]
    )
    assert charge_locals_settled(
        cands, observed_line_charges=["251.00"]
    )


def test_one_cloud_shaped_skips_second():
    row = {
        "field": "total_charge",
        "candidates": [{"engine": "rapidocr", "value": "50.00"}],
        "azure_di_residual": {
            "value": "660.00",
            "currency_shaped": True,
            "review_only": False,
        },
    }
    assert one_cloud_already_shaped(row)
    assert should_skip_second_cloud(row)


def test_vision_residual_counts_as_one_cloud():
    row = {
        "field": "patient_dob",
        "candidates": [],
        "gpt4o_crop_residual": {
            "value": "03/15/1987",
            "shaped": True,
            "review_only": False,
        },
    }
    assert should_skip_second_cloud(row)


def test_kill_switch_disables_ladder(monkeypatch):
    monkeypatch.setenv("CDP_CLOUD_STOP_LADDER", "0")
    row = {
        "field": "total_charge",
        "candidates": [
            {"engine": "rapidocr", "value": "660.00"},
            {"engine": "paddleocr", "value": "660.00"},
        ],
    }
    assert not should_skip_all_cloud("total_charge", row)
    assert not should_skip_second_cloud(
        {
            "azure_di_residual": {
                "value": "660.00",
                "currency_shaped": True,
                "review_only": False,
            }
        }
    )


def test_cascade_accepted_identity_skips_cloud():
    row = {
        "field": "patient_dob",
        "candidates": [{"engine": "rapidocr", "value": "junk"}],
        "cascade": {"accepted": True},
    }
    assert should_skip_all_cloud("patient_dob", row)
    # Weak cascade-accepted ID is not settled — vision may still run.
    id_row = {
        "field": "insured_id_number",
        "candidates": [{"engine": "rapidocr", "value": "Mrieniian"}],
        "cascade": {"accepted": True},
    }
    assert not should_skip_all_cloud("insured_id_number", id_row)


def test_field_authority_codes_cover_monetary_and_identity():
    assert "CHARGE_DI_LOCAL_CONFIRMED" in FIELD_AUTHORITY_CODES
    assert "BOX28_OVER_BLEED_LINE_SUM" in FIELD_AUTHORITY_CODES
    assert "DATE_UNIQUE_CALENDAR_CORROBORATED" in FIELD_AUTHORITY_CODES
    assert field_has_authority(["HARD_VALIDATION_PASSED", "BOX28_OVER_BLEED_LINE_SUM"])
    assert not field_has_authority(["HARD_VALIDATION_PASSED"])


def test_maybe_attach_gpt4o_skips_when_locals_settled(monkeypatch):
    from PIL import Image

    from packages.extraction_recovery.gpt4o_crop_residual import (
        maybe_attach_gpt4o_crop_to_field_row,
    )

    called = {"n": 0}

    class _Boom:
        def recognize_fields(self, *args, **kwargs):
            called["n"] += 1
            raise AssertionError("cloud must not run when locals settled")

    img = Image.new("RGB", (200, 80), "white")
    row = {
        "field": "total_charge",
        "ocr_region": (10, 10, 180, 60),
        "candidates": [
            {"engine": "rapidocr", "value": "660.00"},
            {"engine": "paddleocr", "value": "660.00"},
        ],
        "cascade": {"accepted": False},
    }
    out = maybe_attach_gpt4o_crop_to_field_row(
        row, image=img, gap_class="CHARGE_LOCAL_EXHAUSTED", engine=_Boom()
    )
    assert called["n"] == 0
    assert (out.get("cloud_stop_ladder") or {}).get("skipped") == "LOCALS_SETTLED"
    assert "gpt4o_crop_residual" not in out
