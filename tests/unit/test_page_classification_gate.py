from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from packages.domain.enums import ClaimFormType
from packages.templates.registry import TemplateRegistry
from workers.page_detection.page_classification import classify_page
from workers.page_detection.template_selector import TemplateSelector
from workers.page_detection.router import PageRoutingService
from workers.page_detection.text_extraction import TextLine


def lines(text):
    return [TextLine(text, 0, 0, 100, 100, 1.0)]


def templates():
    r = TemplateRegistry.load_from_directory(canonical_dir=None)
    return r, [r.latest_for_form_type(f) for f in (ClaimFormType.CMS1500, ClaimFormType.UB04)]


def test_separator_precedes_form_anchors_and_explicit_type(monkeypatch):
    registry, forms = templates()
    observed = lines('Document Separator ' + ' '.join(a.phrase for a in forms[0].anchor_definitions))
    page = classify_page(Image.new('L', (100, 100), 255), observed, forms)
    assert (page.page_type, page.status) == ('Separator', 'NON_PROCESSABLE')
    forbidden = Mock(side_effect=AssertionError('Registration must not execute'))
    monkeypatch.setattr('workers.page_detection.template_selector.align_to_reference', forbidden)
    result = TemplateSelector(registry).select([None], text_lines={1: observed}, document_type='CMS1500')
    assert result.reason == 'NON_PROCESSABLE'
    forbidden.assert_not_called()


@pytest.mark.parametrize('index', [0, 1])
def test_existing_form_anchors(index):
    _, forms = templates()
    observed = lines(' '.join(a.phrase for a in forms[index].anchor_definitions))
    result = classify_page(Image.new('L', (100, 100)), observed, forms)
    assert result.page_type == forms[index].form_type.value


def test_blank_attachment_and_unknown():
    _, forms = templates()
    image = Image.new('L', (100, 100), 255)
    assert classify_page(image, [], forms).page_type == 'Blank'
    assert classify_page(image, lines('Attachment: clinical notes'), forms).page_type == 'Attachment'
    assert classify_page(image, lines('unrecognized content'), forms).page_type == 'Unknown'
    image.putpixel((1, 1), 0)
    assert classify_page(image, [], forms).page_type == 'Unknown'


@pytest.mark.parametrize('count', [1, 2])
def test_router_never_registers_separator(count, monkeypatch):
    _, forms = templates()
    forbidden = Mock(side_effect=AssertionError('Registration must not execute'))
    monkeypatch.setattr('workers.page_detection.router.align_to_reference', forbidden)
    extractor = SimpleNamespace(extract=lambda image: lines('Document Separator'))
    image = Image.new('L', (100, 100), 255)
    router = PageRoutingService(*forms, text_extractor=extractor, cms_reference_image=image)
    result = router.route([image] * count)
    assert result.selected_page_number is None
    forbidden.assert_not_called()


def test_classification_only_application_stops(tmp_path, monkeypatch):
    import app
    from io import BytesIO
    from zipfile import ZipFile
    payload = BytesIO()
    Image.new('RGB', (100, 100), 'white').save(payload, format='TIFF')
    archive_path = tmp_path / 'input.zip'
    with ZipFile(archive_path, 'w') as archive:
        archive.writestr('one.tiff', payload.getvalue())
    manager = SimpleNamespace(root=archive_path, describe=lambda: {}, verify=lambda: {'verified': True})
    monkeypatch.setattr(app.DatasetManager, 'load', lambda *args: manager)
    monkeypatch.setattr('workers.cascade.tesseract_adapter.TesseractTextExtractor.extract', lambda *args: lines('Document Separator'))
    forbidden = Mock(side_effect=AssertionError('Routing must not execute'))
    monkeypatch.setattr(PageRoutingService, 'route', forbidden)
    path, state = app.process_one(output_root=tmp_path, classification_only=True)
    assert state['stop_after'] == 'classification'
    assert state['stages']['registration'] == 'SKIPPED'
    assert state['registration_trace']['traces'] == []
    assert state['page_classifications'][0]['status'] == 'NON_PROCESSABLE'
    assert (path.parent / 'classification_report.html').exists()
    forbidden.assert_not_called()


@pytest.mark.parametrize('text,kind', [
    ('Medical Record', 'Medical Record'),
    ('Progress Notes', 'Medical Record'),
    ('Chief Complaint pain History of Present Illness symptoms', 'Medical Record'),
    ('Dear Dr Smith thank you Sincerely Jones', 'Letter'),
    ('diagnosis patient provider', 'Unknown'),
    ('Dear Dr Smith', 'Unknown'),
    ('Dear Dr Smith Medical Record Sincerely Jones', 'Unknown'),
])
def test_explicit_document_classes_with_evidence(text, kind):
    _, forms = templates()
    result = classify_page(Image.new('L', (100, 100), 255), lines(text), forms)
    assert result.page_type == kind
    assert result.evidence['observed_lines'][0]['text'] == text
    if kind != 'Unknown':
        assert result.evidence['rules_matched']


def test_trace_dashboard_serialization_and_escaping(tmp_path):
    import json
    from workers.page_detection.page_classification import write_classification_report
    result = classify_page(Image.new('L', (10, 10)), lines('<script>alert(1)</script>'), [])
    write_classification_report([result], tmp_path)
    trace = json.loads((tmp_path / 'classification_trace.json').read_text())
    assert trace['pages'][0]['class'] == 'Unknown'
    assert trace['pages'][0]['evidence'] == result.evidence
    html = (tmp_path / 'classification_dashboard.html').read_text()
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
