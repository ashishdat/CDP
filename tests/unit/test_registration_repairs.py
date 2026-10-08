import json

import pytest

from packages.recovery.independent_failures import failure_category
from packages.templates.models import AnchorDefinition
from packages.templates.registry import TemplateRegistry
from workers.page_detection.anchor_matching import verify_anchors
from workers.page_detection.text_extraction import TextLine


def line(text, x0=0, y0=0, x1=100, y1=20):
    return TextLine(text=text, x0=x0, y0=y0, x1=x1, y1=y1, confidence=0.9)


def test_required_ub_anchors_are_not_penalized_for_optional_footer_labels():
    template = TemplateRegistry.load_from_directory(canonical_dir=None).get('ub04', '2014')
    result = verify_anchors([line('TYPE OF BILL'), line('STATEMENT COVERS PERIOD')], template.anchor_definitions)
    assert result.all_required_matched
    assert result.confidence == 0.5
    assert result.required_confidence == 1.0
    missing = verify_anchors([line('TYPE OF BILL')], template.anchor_definitions)
    assert not missing.all_required_matched
    assert missing.required_confidence == 0.5


def test_spatially_adjacent_fragments_match_despite_provider_read_order():
    lines = [line('COVERS PERIOD', 150, 8, 260, 28),
             line('OTHER COLUMN', 500, 0, 650, 20),
             line('STATEMENT', 40, 10, 145, 30)]
    result = verify_anchors(lines, [AnchorDefinition(phrase='STATEMENT COVERS PERIOD')])
    assert result.all_required_matched


def test_anchor_detection_does_not_substitute_identifier_like_characters():
    result = verify_anchors([line('STATEMENT COVERS PERI0D')], [
        AnchorDefinition(phrase='STATEMENT COVERS PERIOD')])
    assert not result.all_required_matched


@pytest.mark.parametrize('row,expected', [
    ({'disposition': 'NOT_A_CLAIM_DOCUMENT'}, 'NON_CLAIM_PAGE'),
    ({'disposition': 'REGISTRATION_FAILED', 'unstructured_reg_fallback': {'reason': 'MAILROOM_OR_FAX'}}, 'NON_CLAIM_PAGE'),
    ({'disposition': 'REGISTRATION_FAILED', 'registration_reason': 'NO_TEMPLATE_ABOVE_THRESHOLD', 'registration_attempt_count': 0}, 'TEMPLATE_SELECTION_FAILURE'),
    ({'disposition': 'REGISTRATION_FAILED', 'registration_reason': 'insufficient_inliers', 'registration_attempt_count': 2}, 'ALIGNMENT_FAILURE'),
    ({'disposition': 'REGISTRATION_FAILED', 'registration_reason': 'unsafe_perspective_distortion'}, 'ALIGNMENT_FAILURE'),
    ({'disposition': 'APP_FAILURE', 'registration_reason': 'REGISTRATION_TIMEOUT'}, 'RUNTIME_ERROR'),
    ({'disposition': 'REGISTRATION_FAILED', 'registration_reason': 'UNKNOWN'}, 'UNCLASSIFIED_STAGE_FAILURE'),
    ({'disposition': 'HITL', 'registration_ok': True}, 'FIELD_REVIEW'),
    ({'disposition': 'TRUE_STP', 'registration_ok': True}, 'NONE'),
])
def test_failure_categories_use_stage_evidence(row, expected):
    assert failure_category(row) == expected


def test_ub_reference_has_integrity_checked_public_non_phi_provenance():
    registry = TemplateRegistry.load_from_directory()
    template = registry.get('ub04', '2014')
    image = registry.load_reference_image(template)
    assert image is not None and image.size == (1711, 2216)


def test_stage_diagnostics_distinguish_no_attempt_from_failed_alignment(tmp_path):
    from scripts.run_hackathon_1000_cascade import _registration_stage_diagnostics

    (tmp_path / 'registration_report.json').write_text(json.dumps({'attempt_count': 0}))
    (tmp_path / 'template_discovery.json').write_text(json.dumps({'candidate_templates': [
        {'rejection_reason': ['REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE']}]}))
    result = _registration_stage_diagnostics(tmp_path)
    assert result['registration_attempt_count'] == 0
    assert result['template_rejection_reasons'] == ['REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE']


def test_missing_stage_trace_does_not_invent_zero_alignment_attempts(tmp_path):
    from scripts.run_hackathon_1000_cascade import _registration_stage_diagnostics

    result = _registration_stage_diagnostics(tmp_path)
    assert result['registration_attempt_count'] is None
    assert result['registration_stage_evidence_available'] is False


def test_benchmark_reports_nonclaims_and_three_failure_stages_separately(tmp_path, monkeypatch):
    from scripts import benchmark_hackathon_four_corpora as benchmark
    import scripts.score_hackathon_gt_accuracy as scorer

    monkeypatch.setattr(benchmark, 'OUT', tmp_path)
    monkeypatch.setattr(scorer, 'score', lambda *a: {
        'field_count': 0, 'claims_scored': 0, 'false_accepts': 0})
    run = tmp_path / 'product/corpus_100'
    run.mkdir(parents=True)
    rows = [
        {'document': 'a', 'disposition': 'NOT_A_CLAIM_DOCUMENT'},
        {'document': 'b', 'disposition': 'REGISTRATION_FAILED',
         'registration_reason': 'NO_TEMPLATE_ABOVE_THRESHOLD', 'registration_attempt_count': 0},
        {'document': 'c', 'disposition': 'REGISTRATION_FAILED',
         'registration_reason': 'insufficient_inliers', 'registration_attempt_count': 2},
        {'document': 'd', 'disposition': 'APP_FAILURE', 'error': 'timeout'},
    ]
    (run / 'results.jsonl').write_text(''.join(json.dumps({**r, 'finished': True,
        'completed': False, 'registration_ok': False}) + '\n' for r in rows))
    manifest = {'ground_truth_snapshot': str(tmp_path / 'absent.json'),
                'corpora': [{'pool_size': 100, 'sample_size': 4, 'documents': ['a','b','c','d']}]}
    report = benchmark.summarize(manifest, 'PRODUCT')
    counts = report['overall']
    assert counts['non_claim_document_count'] == 1
    assert counts['template_selection_failure_count'] == 1
    assert counts['alignment_failure_count'] == 1
    assert counts['runtime_error_count'] == 1
    assert counts['registration_failure_count'] == 1
    assert counts['failure_count'] == 3
