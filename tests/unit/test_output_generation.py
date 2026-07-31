"""Output generation: canonical JSON, NSF header records (config-driven,
resolved from a Claim), evidence manifest, reconciliation report, and the
X12 837 adapter's documented not-implemented behavior."""

import json
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.domain.claim import Claim, ServiceLine
from packages.domain.common import BoundingBox
from packages.domain.enums import (
    ClaimFormType,
    ExtractionMethod,
    FieldCriticality,
    ValidationStatus,
)
from packages.domain.extraction import ExtractedField
from packages.domain.validation import ValidationResult
from packages.fixed_width import load_nsf_specs
from workers.output_generation.canonical_json import to_canonical_json, to_canonical_json_bytes
from workers.output_generation.evidence_manifest import build_evidence_manifest
from workers.output_generation.nsf_output import NSFOutputWriter
from workers.output_generation.reconciliation_report import build_reconciliation_report
from workers.output_generation.x12_837 import UnimplementedX12_837Adapter, X12NotImplementedError


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100)


def _sample_claim() -> Claim:
    """Field values match the real Group A sample (see
    docs/DATASET_FINDINGS.md) so this exercises the writer with realistic
    data without embedding a copy of the supplied dataset."""
    field = ExtractedField(
        field_name="patient_name",
        raw_value="KARNO, YOLANA",
        normalized_value="KARNO, YOLANA",
        confidence=0.95,
        page_number=1,
        bounding_box=_bbox(),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
    )
    line = ServiceLine(
        line_number=1,
        procedure_code="96116",
        charge_amount=Decimal("175.00"),
        fields=[field],
    )
    return Claim(
        document_id=uuid4(),
        tenant_id="tenant-1",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1.0",
        patient_name="Karno, Yolana",
        provider_npi="1396827531",
        provider_tax_id="721216996",
        header_fields=[field],
        service_lines=[line],
        total_charge_amount=Decimal("175.00"),
    )


# --- canonical JSON -----------------------------------------------------------------


def test_canonical_json_includes_schema_version_and_claim():
    claim = _sample_claim()
    doc = to_canonical_json(claim)
    assert doc["schema_version"] == "1.0"
    assert doc["claim"]["patient_name"] == "Karno, Yolana"


def test_canonical_json_bytes_are_valid_json():
    claim = _sample_claim()
    data = to_canonical_json_bytes(claim)
    parsed = json.loads(data)
    assert parsed["claim"]["provider_npi"] == "1396827531"


# --- NSF output -----------------------------------------------------------------


def test_nsf_writer_renders_ca0_from_claim_derived_values():
    specs = load_nsf_specs()
    writer = NSFOutputWriter(specs)
    claim = _sample_claim()

    record = writer.render_record("CA0", claim, batch_context={"patient_control_number": "KARY0000"})

    assert len(record) == specs["CA0"].record_length
    assert record.startswith("CA0")
    assert "KARY0000" in record


def test_nsf_writer_batch_context_overrides_source_field():
    specs = load_nsf_specs()
    writer = NSFOutputWriter(specs)
    claim = _sample_claim()

    record = writer.render_record(
        "BA0", claim, batch_context={"provider_tax_id": "999999999"}
    )
    parsed_tax_id = record[31:40]  # provider_tax_id, positions 32-40
    assert parsed_tax_id == "999999999"


def test_nsf_writer_render_available_records_covers_configured_types():
    specs = load_nsf_specs()
    writer = NSFOutputWriter(specs)
    claim = _sample_claim()

    records = writer.render_available_records(claim)

    assert len(records) == len(specs)  # AA0, BA0, BA1, CA0 today
    record_types = {r[:3] for r in records}
    assert record_types == set(specs.keys())
    for record in records:
        assert len(record) == 320


# --- evidence manifest -----------------------------------------------------------------


def test_evidence_manifest_includes_header_and_service_line_fields():
    claim = _sample_claim()
    manifest = build_evidence_manifest(claim)

    assert manifest["claim_id"] == str(claim.claim_id)
    assert len(manifest["header_fields"]) == 1
    assert manifest["header_fields"][0]["field_name"] == "patient_name"
    assert len(manifest["service_lines"]) == 1
    assert manifest["service_lines"][0]["fields"][0]["field_name"] == "patient_name"


# --- reconciliation report -----------------------------------------------------------------


def test_reconciliation_report_summarizes_validation_results():
    claim = _sample_claim()
    results = [
        ValidationResult(
            claim_id=claim.claim_id,
            field_name="total_charge",
            rule_name="service_line_total_reconciliation",
            criticality=FieldCriticality.CRITICAL,
            status=ValidationStatus.VALID,
        ),
        ValidationResult(
            claim_id=claim.claim_id,
            field_name="rendering_provider_npi",
            rule_name="npi_luhn_checksum",
            criticality=FieldCriticality.CRITICAL,
            status=ValidationStatus.INVALID,
            message="bad checksum",
        ),
    ]
    report = build_reconciliation_report(claim, results)

    assert report.valid_count == 1
    assert report.invalid_count == 1
    assert not report.is_clean
    assert report.financial is not None
    assert report.financial.ok  # 175.00 total matches the one 175.00 service line
    assert any("bad checksum" in f for f in report.failures)


# --- X12 837 (not implemented) -----------------------------------------------------------------


def test_x12_837_adapter_raises_documented_not_implemented_error():
    adapter = UnimplementedX12_837Adapter()
    with pytest.raises(X12NotImplementedError):
        adapter.render(_sample_claim())
