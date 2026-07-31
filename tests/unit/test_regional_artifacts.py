from pathlib import Path

from PIL import Image

from packages.domain.common import BoundingBox
from workers.field_candidates.artifacts import (
    CmsAttachmentArtifactNormalizer,
    LaboratoryInvoiceArtifactNormalizer,
    PsychologicalReceiptArtifactNormalizer,
    StatementArtifactNormalizer,
)


def test_artifact_path_comes_from_metadata_not_input_filename(tmp_path: Path):
    source = tmp_path / "misleading_statement_patient.png"
    Image.new("L", (20, 10), 255).save(source)
    artifact = LaboratoryInvoiceArtifactNormalizer().normalize(
        source,
        output_root=tmp_path / "normalized",
        document_id="D-05",
        document_hash="documenthash",
        page_number=2,
        field_name="patient_name",
        source_bbox=BoundingBox(
            x0=0, y0=0, x1=20, y1=10, image_width=20, image_height=10
        ),
        coordinate_frame="ANCHOR_RELATIVE",
        crop_quality=0.98,
        provider_name="laboratory_invoice",
        provider_version="1.0",
    )
    path = Path(artifact.crop_path)
    assert path.is_file()
    assert path.parts[-5:-1] == (
        "documenthash", "2", "laboratory_invoice", "patient_name"
    )
    assert artifact.family == "laboratory_invoice"
    assert artifact.metadata["document_hash"] == "documenthash"


def test_statement_normalizer_uses_common_contract():
    assert StatementArtifactNormalizer().family == "statement"
    assert PsychologicalReceiptArtifactNormalizer().family == "psychological_receipt"
    assert CmsAttachmentArtifactNormalizer().family == "cms_attachment"
