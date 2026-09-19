"""Paddle+rapid agreement counts as independent confirmation for policy."""

from __future__ import annotations

from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence import (
    EvidenceClass,
    EvidencePolicy,
    StructuralLocalizationEvidence,
    StructuralLocalizationType,
    build_evidence_bundle,
)
from packages.ocr.contracts import OCRCandidate
from packages.ocr.provenance import EvidenceProvenance

BOX = BoundingBox(x0=10, y0=10, x1=110, y1=40, image_width=1000, image_height=1200)


def _cand(engine: str, value: str, *, provenance: EvidenceProvenance | None = None) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="1",
        preprocessing_variant="original",
        raw_confidence=0.95,
        calibrated_confidence=0.95,
        bounding_box=BOX,
        latency_ms=1.0,
        provenance=provenance,
    )


def _structure(field: str) -> StructuralLocalizationEvidence:
    return StructuralLocalizationEvidence(
        field_name=field,
        evidence_type=StructuralLocalizationType.TEMPLATE_REGISTRATION_CONFIRMED,
        source="geometry",
        confidence=0.99,
        confirmed=True,
        reason_codes=("TEMPLATE_FIELD_ROI_BOUNDED",),
        field_bbox=(10, 10, 110, 40),
        localization_mode="TEMPLATE",
        positive_bounded_roi=True,
        geometry_valid=True,
    )


def test_paddle_rapid_unknown_lineage_is_independent_confirmation():
    bundle = build_evidence_bundle(
        field_name="patient_name",
        candidates=[
            _cand("paddleocr", "JANE SMITH"),
            _cand("rapidocr", "JANE SMITH"),
        ],
        registration_confidence=0.99,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID", "HARD_VALIDATION_PASSED"},
        hard_validation_passed=True,
        structural_localization=_structure("patient_name"),
    )
    e2 = next(item for item in bundle.items if item.evidence_class is EvidenceClass.E2)
    assert e2.independent is True
    assert e2.evidence_type == "OCR_AGREEMENT_INDEPENDENT"
    assert e2.metadata.get("local_engine_family_confirmation") is True
    satisfied, available, missing, _ = EvidencePolicy.load().evaluate(
        "patient_name", CriticalityLevel.C3, bundle, "CMS1500"
    )
    assert satisfied
    assert set(available) >= {"E2", "E3", "E4"}
    assert "E2" not in missing


def test_correlated_paddle_rapid_still_not_independent():
    shared = EvidenceProvenance(
        page_sha256="page",
        source_representation_id="rep",
        observation_id="obs",
        crop_sha256="crop-shared",
        localization_id="loc",
        localization_method="roi",
        preprocessing_profile="original",
        preprocessing_sha256="prep",
        engine_family="PADDLE_FAMILY",
        model_family="paddle",
        registration_transform_id="reg",
        bbox=BOX,
    )
    rapid_prov = shared.model_copy(
        update={"engine_family": "RAPIDOCR_FAMILY", "model_family": "rapid"}
    )
    bundle = build_evidence_bundle(
        field_name="patient_name",
        candidates=[
            _cand("paddleocr", "JANE SMITH", provenance=shared),
            _cand("rapidocr", "JANE SMITH", provenance=rapid_prov),
        ],
        registration_confidence=0.99,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID"},
        hard_validation_passed=True,
        structural_localization=_structure("patient_name"),
    )
    e2 = next(item for item in bundle.items if item.evidence_class is EvidenceClass.E2)
    assert e2.independent is False
    assert e2.evidence_type == "OCR_AGREEMENT_CORRELATED"
