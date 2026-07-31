"""Field-level evidence manifest: for every field on a claim, where its
value came from (page, bounding box, crop, extraction method/model,
confidence, validation status) -- the audit trail a reviewer or
downstream auditor needs without re-running OCR."""

from __future__ import annotations

from typing import Any

from packages.domain.claim import Claim
from packages.domain.extraction import ExtractedField


def _field_evidence(field: ExtractedField) -> dict[str, Any]:
    return {
        "field_name": field.field_name,
        "raw_value": field.raw_value,
        "normalized_value": field.normalized_value,
        "confidence": field.confidence,
        "page_number": field.page_number,
        "bounding_box": field.bounding_box.model_dump(mode="json"),
        "crop_object_uri": field.crop_object_uri,
        "extraction_method": field.extraction_method.value,
        "model_name": field.model_name,
        "model_version": field.model_version,
        "template_version": field.template_version,
        "validation_status": field.validation_status.value,
        "validation_reasons": field.validation_reasons,
        "escalation_count": field.escalation_count,
    }


def build_evidence_manifest(claim: Claim) -> dict[str, Any]:
    return {
        "claim_id": str(claim.claim_id),
        "document_id": str(claim.document_id),
        "header_fields": [_field_evidence(f) for f in claim.header_fields],
        "service_lines": [
            {
                "line_number": line.line_number,
                "fields": [_field_evidence(f) for f in line.fields],
            }
            for line in claim.service_lines
        ],
    }
