import hashlib
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from packages.extraction_recovery.cloud_stop_ladder import should_skip_second_cloud
from scripts.import_verified_case_labels import import_labels


def test_shaped_cloud_dob_keeps_second_provider_available_until_agreement():
    row = {'field': 'patient_dob', 'candidates': [
        {'engine': 'anthropic_claude_crop', 'value': '05/18/1975'}],
        'gpt4o_crop_residual': {'value': '05/18/1975', 'shaped': True}}
    assert not should_skip_second_cloud(row)
    row['candidates'].append({'engine': 'azure_document_intelligence_read', 'value': '05/18/1975'})
    assert should_skip_second_cloud(row)
    row['attempts'] = [{'engine': 'paddleocr', 'observation': {'parts': {'DD': '13'}}}]
    assert not should_skip_second_cloud(row)


def test_azure_confirmation_does_not_trust_cascade_acceptance(monkeypatch):
    from packages.extraction_recovery import dob_azure_di_residual as residual

    observed = []
    def run(**kwargs):
        observed.append(kwargs['local_accepted'])
        return residual.DobAzureDiResidualResult(attempted=False, configured=False,
            review_only=True, value=None, raw_value=None, date_shaped=False, reason='TEST')
    monkeypatch.setattr(residual, 'run_dob_azure_di_residual', run)
    row = {'field': 'patient_dob', 'ocr_region': [0, 0, 100, 30],
           'cascade': {'accepted': True},
           'candidates': [{'engine': 'paddleocr', 'value': '05/18/1975'}]}
    residual.maybe_attach_dob_azure_di_to_field_row(row, image=Image.new('L', (100, 30)),
                                                  gap_class='EVIDENCE_POLICY_GAP')
    assert observed == [False]


def test_vision_dob_gate_uses_observations_instead_of_shaped_provider_flags():
    from packages.extraction_recovery.gpt4o_crop_residual import dob_needs_gpt4o

    kwargs = dict(local_accepted=True, trocr_shaped=False, azure_di_shaped=True,
                  gap_class='EVIDENCE_POLICY_GAP')
    one = [{'engine': 'azure_document_intelligence_read', 'value': '05/18/1972'}]
    assert dob_needs_gpt4o(**kwargs, candidates=one)
    assert not dob_needs_gpt4o(**kwargs, candidates=one + [
        {'engine': 'anthropic_claude_crop', 'value': '05/18/1972'}])


def test_dob_reader_groups_distinguish_document_read_from_vision_and_keep_rivals(monkeypatch):
    from packages.evidence import builder
    from packages.evidence.models import FieldEvidenceBundle
    from packages.evidence_dependency import DependencyRelation
    from packages.domain.common import BoundingBox
    from packages.ocr.contracts import OCRCandidate

    def candidate(engine, value='05/18/1972'):
        return OCRCandidate(value=value, raw_value=value, engine=engine,
            model_name=engine, model_version='test', preprocessing_variant='test',
            raw_confidence=0.95, calibrated_confidence=None, latency_ms=1,
            bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10,
                                    image_width=100, image_height=100))
    readers = [candidate('azure_document_intelligence_read'), candidate('anthropic_claude_crop')]
    bundle = FieldEvidenceBundle(field_name='patient_dob')
    builder._append_unique_calendar_dob_e2(bundle, 'patient_dob', readers)
    assert len(bundle.items) == 1
    rival = FieldEvidenceBundle(field_name='patient_dob')
    builder._append_unique_calendar_dob_e2(rival, 'patient_dob', readers + [
        candidate('rapidocr', '05/13/1972')])
    assert not rival.items
    monkeypatch.setattr(builder.EvidenceDependencyService, 'classify',
        lambda *args: SimpleNamespace(relation=DependencyRelation.CORRELATED))
    correlated = FieldEvidenceBundle(field_name='patient_dob')
    builder._append_unique_calendar_dob_e2(correlated, 'patient_dob', readers)
    assert not correlated.items


@pytest.mark.parametrize('gap', ['EVIDENCE_POLICY_GAP', 'DOB_COMPONENT_CONFLICT'])
def test_missing_dob_confirmation_reaches_existing_reader_planner(gap):
    from packages.tool_escalation import EscalationTool, plan_field_escalation

    result = plan_field_escalation(gap_class=gap, field_name='patient_dob')
    assert result.tool == EscalationTool.TROCR


def test_verified_label_import_binds_images_and_preserves_unreadable_fields(tmp_path):
    source = tmp_path / 'source.tif'
    source.write_bytes(b'original source bytes')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{'id': 'case-01', 'document': 'Group A/a.tif',
        'original': source.name, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]}))
    labels = tmp_path / 'labels.json'
    labels.write_text(json.dumps({'cases': [{'case_id': 'case-01', 'verified': True,
        'labels': {'member_id': {'status': 'verified', 'value': 'A000000'},
                   'patient_dob': {'status': 'unreadable', 'value': None}}}]}))
    result = import_labels(labels, manifest)
    fields = result['claims']['Group A__a.tif']['fields']
    assert fields['insured_id_number']['value'] == 'A000000'
    assert 'patient_dob' not in fields
    assert len(result['unresolved_fields']) == 1
    assert result['runtime_use_allowed'] is False
    source.write_bytes(b'different image')
    with pytest.raises(ValueError, match='hash'):
        import_labels(labels, manifest)
