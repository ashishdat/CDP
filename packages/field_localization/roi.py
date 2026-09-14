from __future__ import annotations

import json
import re
from hashlib import sha256

from packages.extraction_geometry import ExtractionGeometryDecision
from packages.field_normalization import normalize_icd
from packages.roi_resolution import ROIResolutionMode, ROIResolutionResult
from packages.validation_rules.npi import is_valid_npi

from .contracts import FieldLocationEvidence
from .registration import transform_template_region

_NPI_FIELDS = {
    "provider_npi",
    "billing_provider_npi",
    "rendering_provider_npi",
    "attending_npi",
}
_ICD_FIELDS = {
    "principal_diagnosis",
    "admission_diagnosis",
    "patient_reason_diagnosis",
    "other_diagnosis",
}


def _unique_valid_npis(texts: list[str]) -> set[str]:
    found: set[str] = set()
    for text in texts:
        for match in re.findall(r"\d{10}", text or ""):
            if is_valid_npi(match):
                found.add(match)
    return found


def _npi_candidate_bbox(anchor: FieldLocationEvidence) -> tuple[int, int, int, int] | None:
    for candidate in sorted(anchor.candidates, key=lambda item: item.score, reverse=True):
        if len(_unique_valid_npis([candidate.observed_text or ""])) == 1:
            return candidate.bbox
    texts = [candidate.observed_text or "" for candidate in anchor.candidates]
    if len(_unique_valid_npis(texts)) == 1 and anchor.bbox is not None:
        return anchor.bbox
    return None


def _icd_candidate_bbox(anchor: FieldLocationEvidence) -> tuple[int, int, int, int] | None:
    pattern = re.compile(r"^[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?$")
    for candidate in sorted(anchor.candidates, key=lambda item: item.score, reverse=True):
        value, ok = normalize_icd(candidate.observed_text or "")
        if ok and value and pattern.fullmatch(value):
            return candidate.bbox
    return None


class DynamicROIResolver:
    """Anchor/structure first; registered template is an optional third-priority fast path."""

    version = "dynamic-roi-resolver-v2"

    def resolve(
        self,
        field_name: str,
        *,
        anchor: FieldLocationEvidence | None,
        structural: FieldLocationEvidence | None,
        geometry: ExtractionGeometryDecision,
        registered_template_bbox: tuple[int, int, int, int] | None = None,
        page_size: tuple[int, int] | None = None,
    ) -> ROIResolutionResult:
        if anchor and anchor.wrong_crop_suspected:
            # Label-contaminated NPI crops often still contain one Luhn-valid NPI.
            # Recover that candidate bbox instead of dropping the field.
            if field_name in _NPI_FIELDS:
                recovered = _npi_candidate_bbox(anchor)
                if recovered is not None:
                    return ROIResolutionResult(
                        field_name=field_name,
                        mode=ROIResolutionMode.ANCHOR_RELATIVE,
                        bbox=recovered,
                        field_structural_confidence=max(anchor.confidence, 0.55),
                        reason_codes=(
                            "DYNAMIC_NPI_RECOVERED_FROM_LABEL_CONTAMINATED_CROP",
                            *anchor.reason_codes,
                        ),
                        resolver_version=self.version,
                        localization_evidence_id=anchor.candidate_region_hash,
                    )
            return ROIResolutionResult(
                field_name=field_name,
                mode=ROIResolutionMode.UNRESOLVED,
                reason_codes=("DYNAMIC_ROI_UNRESOLVED", "WRONG_CROP_CANDIDATE_REJECTED",
                              *anchor.reason_codes),
                resolver_version=self.version,
                localization_evidence_id=anchor.candidate_region_hash,
            )
        ownership_fail_closed = bool(
            anchor
            and anchor.region_ownership in {"UNKNOWN", "REGION_AMBIGUOUS"}
            and anchor.locator_version.startswith("field-locator-v4")
        )
        if ownership_fail_closed:
            if field_name in _ICD_FIELDS:
                recovered = _icd_candidate_bbox(anchor)
                if recovered is not None:
                    return ROIResolutionResult(
                        field_name=field_name,
                        mode=ROIResolutionMode.ANCHOR_RELATIVE,
                        bbox=recovered,
                        field_structural_confidence=max(anchor.confidence, 0.55),
                        reason_codes=(
                            "DYNAMIC_ICD_RECOVERED_FROM_OWNERSHIP_UNPROVEN",
                            *anchor.reason_codes,
                        ),
                        resolver_version=self.version,
                        localization_evidence_id=anchor.candidate_region_hash,
                    )
            if field_name in _NPI_FIELDS:
                recovered = _npi_candidate_bbox(anchor)
                if recovered is not None:
                    return ROIResolutionResult(
                        field_name=field_name,
                        mode=ROIResolutionMode.ANCHOR_RELATIVE,
                        bbox=recovered,
                        field_structural_confidence=max(anchor.confidence, 0.55),
                        reason_codes=(
                            "DYNAMIC_NPI_RECOVERED_FROM_OWNERSHIP_UNPROVEN",
                            *anchor.reason_codes,
                        ),
                        resolver_version=self.version,
                        localization_evidence_id=anchor.candidate_region_hash,
                    )
            return ROIResolutionResult(
                field_name=field_name,
                mode=ROIResolutionMode.UNRESOLVED,
                reason_codes=("DYNAMIC_ROI_UNRESOLVED", "REGION_OWNERSHIP_UNPROVEN",
                              *anchor.ownership_reason_codes),
                resolver_version=self.version,
                localization_evidence_id=anchor.candidate_region_hash,
            )
        if (anchor and anchor.method == ROIResolutionMode.ANCHOR_RELATIVE and anchor.bbox
                and not anchor.wrong_crop_suspected):
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.ANCHOR_RELATIVE,
                bbox=anchor.bbox, field_structural_confidence=anchor.confidence,
                reason_codes=("DYNAMIC_PRIORITY_1_ANCHOR", *anchor.reason_codes),
                resolver_version=self.version,
                localization_evidence_id=anchor.candidate_region_hash,
            )
        if structural and structural.method == ROIResolutionMode.STRUCTURAL_REGION and structural.bbox:
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.STRUCTURAL_REGION,
                bbox=structural.bbox, field_structural_confidence=structural.confidence,
                reason_codes=("DYNAMIC_PRIORITY_2_STRUCTURE", *structural.reason_codes),
                resolver_version=self.version,
            )
        registration = geometry.registration
        registered_safe = bool(
            geometry.authorizes_fixed_roi
            and geometry.form_identity.status.value == "VERIFIED"
            and geometry.compatibility is not None
            and geometry.compatibility.status.value != "INCOMPATIBLE"
            and registration is not None
            and registration.accepted
            and registration.corner_validity is True
            and geometry.transformed_geometry_valid
            and registration.alignment_confidence >= 0.80
        )
        if registered_safe and registered_template_bbox:
            mapped_bbox = registered_template_bbox
            transform = registration.transform_matrix if registration else None
            if transform:
                transformed = transform_template_region(
                    registered_template_bbox, transform, page_size
                )
                if not transformed.valid or transformed.bbox is None:
                    return ROIResolutionResult(
                        field_name=field_name, mode=ROIResolutionMode.UNRESOLVED,
                        reason_codes=("REGISTERED_TEMPLATE_TRANSFORM_INVALID",
                                      transformed.reason_code),
                        resolver_version=self.version,
                    )
                mapped_bbox = transformed.bbox
            x0, y0, x1, y1 = mapped_bbox
            bounded = x1 > x0 and y1 > y0 and x0 >= 0 and y0 >= 0
            if not bounded:
                return ROIResolutionResult(
                    field_name=field_name, mode=ROIResolutionMode.UNRESOLVED,
                    reason_codes=("REGISTERED_TEMPLATE_ROI_INVALID",),
                    resolver_version=self.version,
                )
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.FIXED_REGISTERED,
                bbox=mapped_bbox,
                field_structural_confidence=registration.alignment_confidence,
                reason_codes=("DYNAMIC_PRIORITY_3_TEMPLATE_FAST_PATH",),
                resolver_version=self.version,
                template_id=geometry.template_id,
                registration_method=registration.algorithm,
                registration_confidence=registration.alignment_confidence,
                registration_transform_hash=sha256(json.dumps(
                    registration.transform_matrix, sort_keys=True
                ).encode()).hexdigest() if registration.transform_matrix else None,
                source_coordinates=registered_template_bbox,
                mapped_coordinates=mapped_bbox,
            )
        return ROIResolutionResult(
            field_name=field_name, mode=ROIResolutionMode.UNRESOLVED,
            reason_codes=("DYNAMIC_ROI_UNRESOLVED",), resolver_version=self.version,
        )
