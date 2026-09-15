"""Unit tests for field-cascade-v7 strategy loading, E3 honesty, crop ladders."""

from __future__ import annotations

import json
from pathlib import Path

from packages.extraction_recovery.field_cascade import FieldCascade, crop_variants
from packages.extraction_recovery.gap_taxonomy import classify_field_gap
from packages.extraction_recovery.strategy import (
    crop_ladder_for,
    load_cascade_strategy,
    post_miss_for,
)
from scripts.complete_from_extraction import _load_registration_context


def test_strategy_is_v7():
    load_cascade_strategy.cache_clear()
    strategy = load_cascade_strategy()
    assert strategy.strategy_id == "field-cascade-v7"
    assert strategy.status == "ACTIVE"
    assert strategy.phase == 7
    assert "EVIDENCE_PLUMBING_GAP" in strategy.gap_classes
    assert any(s.get("id") == "complete_e3" for s in strategy.stages)


def test_dob_ladder_includes_year_wide_and_post_miss_cells():
    assert crop_ladder_for("patient_dob") == (
        "primary",
        "dob_digit_band",
        "dob_loose",
        "dob_year_wide",
    )
    assert "dob_cells" in post_miss_for("patient_dob")


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


def test_field_cascade_defaults_to_v7():
    assert FieldCascade().strategy_id == "field-cascade-v7"


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
