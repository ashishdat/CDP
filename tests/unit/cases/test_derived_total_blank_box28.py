"""Box 28 blankness + derived total from complete verified lines."""

from decimal import Decimal

from PIL import Image, ImageDraw

from packages.claim_evidence.box28_blankness import (
    Box28Blankness,
    classify_box28_blankness,
)
from packages.claim_evidence.derived_total_authority import (
    evaluate_derived_total_from_complete_verified_lines,
)
from packages.claim_evidence.financial_geometry_authority import (
    evaluate_financial_geometry_arithmetic,
)
from packages.claim_evidence.line_charge_selector import apply_line_charge_selector


_CHARGE_BBOX = (1050.0, 1458.0, 1180.0, 1513.0)


def _cand(engine, value, raw=None, bbox=None):
    payload = {
        "engine": engine,
        "value": value,
        "raw_value": raw if raw is not None else value,
    }
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        payload["bounding_box"] = {
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "image_width": 1712,
            "image_height": 2214,
        }
    return payload


def _blank_roi() -> Image.Image:
    """Near-white Box 28 crop with only a dashed underline (ruling-only)."""
    img = Image.new("L", (200, 50), color=245)
    draw = ImageDraw.Draw(img)
    y = 40
    for x in range(10, 190, 8):
        draw.line([(x, y), (x + 4, y)], fill=40, width=1)
    return img


def _ink_roi() -> Image.Image:
    img = Image.new("L", (200, 50), color=245)
    draw = ImageDraw.Draw(img)
    draw.text((40, 10), "270.00", fill=20)
    return img


def test_ocr_empty_alone_is_not_confirmed_blank():
    decision = classify_box28_blankness(
        box28_amount=None,
        field_payload={"candidates": []},
        region=(1045.0, 1825.0, 1248.0, 1875.0),
    )
    assert decision.status == Box28Blankness.UNCLASSIFIED
    assert decision.reason == "OCR_EMPTY_WITHOUT_INK_ANALYSIS"


def test_roi_ink_analysis_confirms_blank():
    decision = classify_box28_blankness(
        box28_amount=None,
        field_payload={"candidates": []},
        region=(1045.0, 1825.0, 1248.0, 1875.0),
        roi_image=_blank_roi(),
    )
    assert decision.status == Box28Blankness.CONFIRMED_BLANK


def test_currency_shaped_ocr_is_never_blank():
    decision = classify_box28_blankness(
        box28_amount="270.00",
        field_payload={
            "candidates": [_cand("paddleocr", "270.00", "270.00")],
        },
        region=(1045.0, 1825.0, 1248.0, 1875.0),
        roi_image=_blank_roi(),
    )
    assert decision.status == Box28Blankness.INK_OBSERVED
    assert decision.reason == "CURRENCY_SHAPED_OCR_PRESENT"


def test_box28_label_only_ocr_is_confirmed_blank():
    """Caption/ruling OCR (``8.TOTAL CHARGE``) is not printed amount ink."""
    decision = classify_box28_blankness(
        box28_amount="8.00",
        field_payload={
            "ranked_candidate": {
                "ocr_candidate": {
                    "value": "8.TOTAL CHARGE",
                    "raw_value": "8.TOTAL CHARGE 2",
                }
            },
            "candidates": [
                {"value": "8.00", "raw_value": "8.00", "engine": "paddleocr"},
                {
                    "value": "8.TOTAL CHARGE",
                    "raw_value": "2\n8.TOTAL CHARGE\nACnnn",
                    "engine": "rapidocr",
                },
            ],
            "attempts": [
                {"observation": {"text": "8.TOTAL CHARGE"}},
                {"observation": {"text": "2!\nB.TOTAL CHARGE"}},
            ],
        },
        region=(1045.0, 1825.0, 1248.0, 1875.0),
    )
    assert decision.status == Box28Blankness.CONFIRMED_BLANK
    assert decision.reason == "BOX28_LABEL_ONLY_NO_AMOUNT_INK"


def test_financial_geometry_same_stem_cents_twin():
    """``346.04`` beside Σ ``346.00`` is a same-stem OCR twin, not HITL."""
    lines = [
        {
            "charges": "346.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "346.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "346.00", "346.00", _CHARGE_BBOX),
                _cand("rapidocr", "346.00", "346.00", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="346.04",
        service_lines=lines,
        box28_observation={
            "text": "346.04",
            "raw_digit_sequence": "34604",
            "canonical_monetary_value": "346.04",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "346.04"
    assert decision.details.get("same_stem_cents_twin") is True


def test_financial_geometry_skips_ambiguous_lines_in_sum():
    """Ambiguous rows must not veto FG confirmation of clean selected lines."""
    lines = [
        {
            "charges": "270.00",
            "procedure_code": "99213",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "270.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "270.00", "270.00", _CHARGE_BBOX),
                _cand("rapidocr", "270.00", "270.00", _CHARGE_BBOX),
            ],
        },
        {
            "charges": None,
            "procedure_code": "99214",
            "line_charge_selection": {
                "disposition": "AMBIGUOUS_LINE_CHARGE",
                "amount": None,
                "reason": "ONLY_BLEED_OR_SOUP_CANDIDATES",
            },
            "candidates": [
                _cand("paddleocr", "141.00", "14100", _CHARGE_BBOX),
            ],
        },
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="270.00",
        service_lines=lines,
        box28_observation={
            "text": "270.00",
            "raw_digit_sequence": "27000",
            "canonical_monetary_value": "270.00",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "270.00"


def test_ink_present_unreadable_blocks_derive():
    decision = evaluate_derived_total_from_complete_verified_lines(
        document_family="CMS1500",
        registration_verified=True,
        service_lines=[
            {
                "procedure_code": "99213",
                "charges": "270.00",
                "canonical_region": list(_CHARGE_BBOX),
                "line_charge_selection": {
                    "disposition": "SELECTED_LOCAL_CHARGE",
                    "amount": "270.00",
                    "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                    "supporting_engines": ["paddleocr", "rapidocr"],
                },
                "candidates": [
                    _cand("paddleocr", "270.00", "270.00", _CHARGE_BBOX),
                    _cand("rapidocr", "270.00", "270.00", _CHARGE_BBOX),
                ],
            }
        ],
        blankness_status="INK_PRESENT_UNREADABLE",
    )
    assert not decision.derived
    assert decision.reason == "BOX28_INK_PRESENT_UNREADABLE"


def test_derived_total_from_confirmed_blank_verified_lines():
    lines = apply_line_charge_selector(
        [
            {
                "procedure_code": "99213",
                "charges": "135.00",
                "canonical_region": list(_CHARGE_BBOX),
                "candidates": [
                    _cand("paddleocr", "135.00", "135.00", _CHARGE_BBOX),
                    _cand("rapidocr", "135.00", "135.00", _CHARGE_BBOX),
                ],
            },
            {
                "procedure_code": "99214",
                "charges": "135.00",
                "canonical_region": [1050.0, 1513.0, 1180.0, 1568.0],
                "candidates": [
                    _cand(
                        "paddleocr",
                        "135.00",
                        "135.00",
                        (1050.0, 1513.0, 1180.0, 1568.0),
                    ),
                    _cand(
                        "rapidocr",
                        "135.00",
                        "135.00",
                        (1050.0, 1513.0, 1180.0, 1568.0),
                    ),
                ],
            },
        ]
    )
    decision = evaluate_derived_total_from_complete_verified_lines(
        document_family="CMS1500",
        registration_verified=True,
        service_lines=lines,
        blankness_status="CONFIRMED_BLANK",
    )
    assert decision.derived
    assert decision.amount == "270.00"
    assert decision.reason == "DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES"
    assert decision.details["value_origin"] == "DERIVED_FROM_VERIFIED_SERVICE_LINES"
    assert decision.details["printed_box28_value"] is None


def test_ambiguous_line_blocks_derive():
    lines = [
        {
            "procedure_code": "99213",
            "charges": "49.72",
            "canonical_region": list(_CHARGE_BBOX),
            "line_charge_selection": {
                "disposition": "AMBIGUOUS_LINE_CHARGE",
                "amount": None,
                "reason": "ONLY_BLEED_OR_SOUP_CANDIDATES",
            },
            "candidates": [
                _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_derived_total_from_complete_verified_lines(
        document_family="CMS1500",
        registration_verified=True,
        service_lines=lines,
        blankness_status="CONFIRMED_BLANK",
    )
    assert not decision.derived
    assert "AMBIGUOUS" in decision.reason


def test_financial_geometry_ignores_same_roi_junk_tail():
    """``34 125`` → ``125.00`` beside confirmed ``34.25`` is ROI soup, not conflict."""
    lines = [
        {
            "charges": "34.25",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "34.25",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "34.25", "34.25", _CHARGE_BBOX),
                _cand("rapidocr", "34.25", "34.25", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="34.25",
        service_lines=lines,
        box28_field_payload={
            "ranked_candidate": {
                "ocr_candidate": {"value": "34.25", "raw_value": "34.25"}
            },
            "alternatives": [
                {"ocr_candidate": {"value": "25.00", "raw_value": "34 25\n$"}},
                {"ocr_candidate": {"value": "125.00", "raw_value": "V.\n34 125"}},
            ],
        },
        box28_observation={
            "text": "34.25",
            "raw_digit_sequence": "3425",
            "canonical_monetary_value": "34.25",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "34.25"


def test_financial_geometry_ignores_same_roi_competing_engine_soup():
    """``43800`` → ``438.00`` beside agreeing ``135.00`` is same-ROI engine soup."""
    lines = [
        {
            "charges": "135.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "135.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "135.00", "135.00", _CHARGE_BBOX),
                _cand("rapidocr", "135.00", "135.00", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="135.00",
        service_lines=lines,
        box28_field_payload={
            "ranked_candidate": {
                "ocr_candidate": {"value": "135.00", "raw_value": "135 00"}
            },
            "alternatives": [
                {"ocr_candidate": {"value": "438.00", "raw_value": "43800"}},
            ],
            "candidates": [
                {"value": "135.00", "raw_value": "135 00", "engine": "rapidocr"},
                {"value": "438.00", "raw_value": "43800", "engine": "paddleocr"},
            ],
            "attempts": [
                {"engine": "tesseract_digits", "observation": {"text": "43800"}},
                {"engine": "rapidocr", "observation": {"text": "135 00"}},
            ],
        },
        box28_observation={
            "text": "135 00",
            "raw_digit_sequence": "13500",
            "canonical_monetary_value": "135.00",
            "raw_tokens": ["135 00", "43800"],
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "135.00"
    assert decision.reason == "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED"


def test_financial_geometry_relieves_box28_single_junk_digit():
    """``$400300`` beside clean Σ ``400.00`` is one junk digit, not a true total."""
    lines = [
        {
            "charges": "200.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "200.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "200.00", "200.00", _CHARGE_BBOX),
                _cand("rapidocr", "200.00", "200.00", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "200.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "200.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "200.00", "200.00", _CHARGE_BBOX),
                _cand("rapidocr", "200.00", "200.00", _CHARGE_BBOX),
            ],
        },
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="400.40",
        service_lines=lines,
        box28_field_payload={
            "ranked_candidate": {
                "ocr_candidate": {"value": "400.40", "raw_value": "40040"}
            },
            "alternatives": [
                {"ocr_candidate": {"value": "4003.00", "raw_value": "$400300"}},
            ],
            "candidates": [
                {"value": "400.40", "raw_value": "40040"},
                {"value": "4003.00", "raw_value": "$400300"},
            ],
            "attempts": [
                {"observation": {"text": "$400300"}},
                {"observation": {"text": "40040"}},
            ],
        },
    )
    assert decision.confirmed
    # Printed same-stem twin keeps Box 28; junk-digit raw relief applies when
    # there is no same-stem shaped amount (see junk-digit-only case below).
    assert decision.amount == "400.40"
    assert decision.details.get("same_stem_cents_twin") is True


def test_financial_geometry_relieves_box28_single_junk_digit_raw_only():
    """Raw ``$400300`` with no clean disagreeing currency rival → adopt Σ ``400.00``."""
    from packages.claim_evidence.financial_geometry_authority import (
        evaluate_financial_geometry_arithmetic,
    )

    lines = [
        {
            "charges": "200.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "200.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "200.00", "200.00", _CHARGE_BBOX),
                _cand("rapidocr", "200.00", "200.00", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "200.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "200.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "200.00", "200.00", _CHARGE_BBOX),
                _cand("rapidocr", "200.00", "200.00", _CHARGE_BBOX),
            ],
        },
    ]
    decision = evaluate_financial_geometry_arithmetic(
        # Digit soup without a clean ``\d+\.\d{2}`` rival that would veto relief.
        box28_amount="40040",
        service_lines=lines,
        box28_field_payload={
            "ranked_candidate": {
                "ocr_candidate": {"value": "40040", "raw_value": "$400300"}
            },
            "candidates": [
                {"value": "40040", "raw_value": "$400300"},
            ],
            "attempts": [
                {"observation": {"text": "$400300"}},
            ],
        },
    )
    assert decision.confirmed
    assert decision.amount == "400.00"
    assert decision.details.get("box28_raw_junk_digit_relieved") is True


def test_names_agree_confusable_insertion_twins():
    from packages.geometry_authority.form_redundancy import (
        names_agree,
        reconcile_box2_box4_names,
    )

    assert names_agree("FRANCAVLLA, THOMAS J", "FRANCAVILLA. THOMAS J")
    assert names_agree("RENTER, ROVINSKI", "RENTER. ROVINSK")
    # Explicit non-Self keeps BOX2↔4 E6 gated even when names soft-match.
    recon_spouse = reconcile_box2_box4_names(
        "FRANCAVLLA, THOMAS J",
        "FRANCAVILLA. THOMAS J",
        relationship="SPOUSE",
    )
    assert not recon_spouse.agreed
    assert recon_spouse.reason == "RELATIONSHIP_NOT_SELF"
    # Self + confusable twins confirm Box 2↔4.
    recon_self = reconcile_box2_box4_names(
        "FRANCAVLLA, THOMAS J",
        "FRANCAVILLA. THOMAS J",
        relationship="SELF",
    )
    assert recon_self.agreed
    assert recon_self.reason == "BOX2_BOX4_SELF_AGREE"
    assert not reconcile_box2_box4_names(
        "REMS KEVIN IOHN",
        "BRYANT BURRUS-JOYCE",
        relationship="SELF",
    ).agreed


def test_financial_geometry_soft_integrity_when_exact_match():
    """Glyph integrity failure must not block already-agreeing Σ == Box28."""
    lines = [
        {
            "charges": "34.25",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "34.25",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
                "supporting_engines": ["paddleocr", "rapidocr"],
            },
            "candidates": [
                _cand("paddleocr", "34.25", "34.25", _CHARGE_BBOX),
                _cand("rapidocr", "34.25", "34.25", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="34.25",
        service_lines=lines,
        box28_observation={
            "text": "34.25",
            "raw_digit_sequence": "3425",  # weak glyph mapping
            "canonical_monetary_value": "34.25",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "34.25"
