"""Self-twin inject must not invent patient_name conflicts."""

from __future__ import annotations

from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate


def _cand(engine: str, value: str) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="test",
        preprocessing_variant="test",
        raw_confidence=0.9,
        calibrated_confidence=0.9,
        bounding_box=BoundingBox(
            x0=0, y0=0, x1=10, y1=10, image_width=20, image_height=20
        ),
        latency_ms=0.0,
    )


def test_self_checkbox_divergent_insured_not_injected_as_patient_rival():
    """Self + divergent Box4 OCR must not mint INSURED_NAME_SELF_TWIN conflict."""
    # Exercise the inject predicate via the same helpers complete_from_extraction uses.
    from packages.candidate_reconciliation.reconciler import _name_is_strong_person
    from packages.geometry_authority.form_redundancy import (
        names_agree,
        relationship_is_self,
    )

    patient = "CHANAUICNI ARUA. M"
    insured = "CRMAUIANI AIAY M"
    assert relationship_is_self("SELF") is True
    assert _name_is_strong_person(insured) is True
    # Soft twin required for inject — these do not agree.
    assert names_agree(patient, insured) is False


def test_soft_twin_names_still_agree_for_inject():
    from packages.geometry_authority.form_redundancy import names_agree

    assert names_agree("FRANCAVILLA, MARIA", "FRANCAVLLA, MARIA") is True


def test_name_fragment_second_family_counts_as_soft_e2():
    from packages.candidate_reconciliation.reconciler import (
        _name_soft_equivalent_second_family,
    )

    cands = [
        _cand("paddleocr", "NOVOTNY. FINNIE"),
        _cand("rapidocr", "NOVOTNY"),
    ]
    assert _name_soft_equivalent_second_family("NOVOTNY. FINNIE", cands) is True


def test_name_soft_equivalent_mints_e2_evidence():
    from packages.evidence.builder import build_evidence_bundle

    bundle = build_evidence_bundle(
        field_name="patient_name",
        candidates=[
            _cand("paddleocr", "NOVOTNY. FINNIE"),
            _cand("rapidocr", "NOVOTNY"),
        ],
        registration_confidence=0.9,
        wrong_crop_suspected=False,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"},
        hard_validation_passed=True,
    )
    e2 = [
        item
        for item in bundle.items
        if item.evidence_class.name == "E2" and item.independent
    ]
    assert e2
    assert any(
        (item.metadata or {}).get("agreement_type") == "NAME_SOFT_EQUIVALENT_FAMILY"
        for item in e2
    )
