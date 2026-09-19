"""Unit tests for field-cascade-v11 strategy loading, E3 honesty, crop ladders."""

from __future__ import annotations

import json
from pathlib import Path

from packages.extraction_recovery.field_cascade import (
    FieldCascade,
    crop_variants,
    pick_engine_candidates,
)
from packages.extraction_recovery.gap_taxonomy import classify_field_gap
from packages.extraction_recovery.strategy import (
    crop_ladder_for,
    load_cascade_strategy,
    post_miss_for,
)
from scripts.complete_from_extraction import _load_registration_context


def test_strategy_is_v11():
    load_cascade_strategy.cache_clear()
    strategy = load_cascade_strategy()
    assert strategy.strategy_id == "field-cascade-v11"
    assert strategy.status == "ACTIVE"
    assert strategy.phase == 11
    assert "EVIDENCE_PLUMBING_GAP" in strategy.gap_classes
    assert "CALIBRATION_HITL" in strategy.gap_classes
    assert "DOB_SEPARATOR_ARTIFACT" in strategy.gap_classes
    assert any(s.get("id") == "complete_e3" for s in strategy.stages)
    assert any(s.get("id") == "register_recovery" for s in strategy.stages)
    assert any(s.get("id") == "engine_agreement" for s in strategy.stages)
    assert any(s.get("id") == "dob_cells_first" for s in strategy.stages)
    assert any(s.get("id") == "dob_separator_relief" for s in strategy.stages)
    assert any(s.get("id") == "name_label_relief" for s in strategy.stages)
    assert strategy.defaults.get("confirmation_required_usable") == 1


def test_dob_ladder_includes_year_wide_and_post_miss_cells():
    assert crop_ladder_for("patient_dob") == (
        "primary",
        "dob_digit_band",
        "dob_loose",
        "dob_year_wide",
    )
    assert "dob_cells" in post_miss_for("patient_dob")


def test_name_ladder_prefers_value_band():
    assert crop_ladder_for("insured_name")[0] == "name_value_band"
    assert crop_ladder_for("patient_name")[0] == "name_value_band"
    assert crop_ladder_for("insured_id_number")[0] == "id_value_band"


def test_crop_variants_follow_strategy_order():
    variants = crop_variants(
        "patient_dob",
        (672, 424, 871, 457),
        {"x0": 667, "y0": 402, "x1": 886, "y1": 459},
        (1700, 2200),
    )
    ids = [v.variant_id for v in variants]
    assert ids[0] == "primary"
    assert "dob_digit_band" in ids
    assert "dob_year_wide" in ids
    ladder = list(crop_ladder_for("patient_dob"))
    present = [vid for vid in ladder if vid in ids]
    assert ids == present


def test_field_cascade_defaults_to_v11():
    load_cascade_strategy.cache_clear()
    assert FieldCascade().strategy_id == "field-cascade-v11"


def test_pick_prefers_confirmation_when_primary_is_header_bleed():
    """v9: do not stop on primary header bleed when confirmation is DATE_SHAPED."""
    candidates = [
        {
            "value": "MM L 29",
            "raw_value": "MM\nL\n29",
            "engine": "paddleocr",
            "raw_confidence": 0.7,
        },
        {
            "value": "09/29/1996",
            "raw_value": "09/29/1996",
            "engine": "rapidocr",
            "raw_confidence": 0.85,
        },
    ]
    selected, _raw, reason, ordered = pick_engine_candidates("patient_dob", candidates)
    assert selected == "09/29/1996"
    assert "DATE_SHAPED" in reason
    assert ordered[0]["engine"] == "rapidocr"


def test_pick_prefers_multi_engine_agreement():
    candidates = [
        {
            "value": "OSC75491075",
            "raw_value": "OSC75491075",
            "engine": "paddleocr",
            "raw_confidence": 0.9,
        },
        {
            "value": "OSC75491075",
            "raw_value": "OSC75491075\n",
            "engine": "rapidocr",
            "raw_confidence": 0.88,
        },
    ]
    selected, _raw, reason, ordered = pick_engine_candidates(
        "insured_id_number", candidates
    )
    assert selected == "OSC75491075"
    assert reason.startswith("MULTI_ENGINE_AGREEMENT:")
    assert ordered[0]["engine"] == "paddleocr"


def test_gap_taxonomy_marks_observed_name_policy_hold_not_handwriting():
    gap = classify_field_gap(
        "patient_name",
        observed_text="CAMARATO JOSHUA",
        accepted=False,
        reason_codes=[
            "HARD_VALIDATION_PASSED",
            "MISSING_E6_CROSS_FIELD_CONFIRMATION",
            "ACQUIRE_E4",
        ],
    )
    assert gap is not None
    assert gap.gap_class == "EVIDENCE_POLICY_GAP"
    assert "CAMARATO" not in gap.evidence


def test_gap_taxonomy_marks_name_conflict_not_handwriting():
    gap = classify_field_gap(
        "patient_name",
        observed_text="THOMAS DARLENE",
        accepted=False,
        reason_codes=[
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "CONFLICT_MARGIN_TOO_SMALL",
        ],
    )
    assert gap is not None
    assert gap.gap_class == "NAME_ENGINE_CONFLICT"
    assert "THOMAS" not in gap.evidence


def test_gap_taxonomy_empty_name_stays_unreadable():
    gap = classify_field_gap(
        "patient_name",
        observed_text="",
        accepted=False,
        reason_codes=["NO_NONEMPTY_CANDIDATE"],
    )
    assert gap is not None
    assert gap.gap_class == "HANDWRITING_UNREADABLE"


def test_gap_taxonomy_marks_header_only_dob_as_handwriting():
    gap = classify_field_gap(
        "patient_dob",
        observed_text="Mly DD",
        accepted=False,
    )
    assert gap is not None
    assert gap.gap_class == "HANDWRITING_UNREADABLE"


def test_gap_taxonomy_marks_missing_e3_as_plumbing_not_handwriting():
    gap = classify_field_gap(
        "patient_name",
        observed_text="THOMAS DARLENE",
        accepted=False,
        reason_codes=[
            "HARD_VALIDATION_PASSED",
            "MISSING_E3_REGISTRATION_EVIDENCE",
            "ACQUIRE_E3",
        ],
    )
    assert gap is not None
    assert gap.gap_class == "EVIDENCE_PLUMBING_GAP"


def test_gap_taxonomy_marks_engine_authority_strip_as_plumbing():
    gap = classify_field_gap(
        "patient_dob",
        observed_text="",
        accepted=False,
        reason_codes=[
            "NO_NONEMPTY_CANDIDATE",
            "CANDIDATE_ENGINE_NOT_AUTHORIZED:ANY.patient_dob.paddleocr.rapidocr.v1",
        ],
    )
    assert gap is not None
    assert gap.gap_class == "EVIDENCE_PLUMBING_GAP"


def test_gap_taxonomy_marks_calibration_hold_honestly():
    gap = classify_field_gap(
        "patient_dob",
        observed_text="1993-03-31",
        accepted=False,
        reason_codes=[
            "HARD_VALIDATION_PASSED",
            "DATE_VALID",
            "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD",
        ],
    )
    assert gap is not None
    assert gap.gap_class == "CALIBRATION_HITL"


def test_complete_loads_e3_from_registration_report(tmp_path: Path):
    app = tmp_path / "application"
    app.mkdir()
    geometry = {
        "type": "GeometryResult",
        "status": "SUCCESS",
        "fields": [
            {
                "field": "patient_name",
                "result": {
                    "registration": {"accepted": True},
                    "aligned_roi": {"x0": 1, "y0": 2, "x1": 10, "y1": 20},
                },
            }
        ],
    }
    (app / "GeometryResult.json").write_text(json.dumps(geometry), encoding="utf-8")
    report = {
        "report_type": "RegistrationReport",
        "attempts": [
            {
                "acceptance": {"accepted": True, "score": 0.46},
                "raw_evidence": {"alignment_confidence": 0.46},
            }
        ],
    }
    (app / "registration_report.json").write_text(json.dumps(report), encoding="utf-8")
    extraction = {
        "source_artifacts": {
            "geometry": {"path": str(app / "GeometryResult.json")},
        }
    }
    conf, locs, warns = _load_registration_context(extraction)
    assert conf is not None and conf >= 0.80
    assert "patient_name" in locs
    assert locs["patient_name"].confirmed is True
    assert warns == []
