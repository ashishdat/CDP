"""Page identity from existing classification text; never invokes registration."""
from dataclasses import asdict, dataclass, field
from html import escape
import json
import re
from pathlib import Path

from workers.page_detection.anchor_matching import verify_anchors


@dataclass(frozen=True)
class PageClassificationResult:
    page_number: int
    page_type: str
    confidence: float
    reason: str
    status: str
    evidence: dict = field(default_factory=dict)


def is_separator(lines):
    text = re.sub(r'[^A-Z0-9]+', ' ', ' '.join(line.text for line in lines).upper())
    return bool(re.search(r'\bDOCUMENT SEPARATOR\b', text))


def classify_page(image, lines, templates, page_number=1):
    lines = list(lines)
    text = re.sub(r"\s+", " ", " ".join(line.text for line in lines).upper()).strip()
    evidence = {
        "observed_lines": [{"text": line.text, "confidence": line.confidence,
                            "bbox": [line.x0, line.y0, line.x1, line.y1]} for line in lines],
        "rules_matched": [], "form_anchors": [],
        "confidence_basis": "Rule support, not calibrated probability",
    }

    def result(kind, confidence, reason, status, rules):
        evidence["rules_matched"] = rules
        return PageClassificationResult(page_number, kind, confidence, reason, status, evidence)

    if is_separator(lines):
        return result('Separator', 1.0, 'Explicit Document Separator marker',
                      'NON_PROCESSABLE', ['DOCUMENT SEPARATOR'])
    with image.convert('L') as gray:
        extrema = gray.getextrema()
    evidence['grayscale_extrema'] = list(extrema)
    if not lines and extrema == (255, 255):
        return result('Blank', 1.0, 'Uniform white page with no text',
                      'NON_PROCESSABLE', ['UNIFORM_WHITE', 'NO_TEXT'])
    matches = [(template, verify_anchors(lines, template.anchor_definitions)) for template in templates]
    evidence['form_anchors'] = [
        {'template_id': t.template_id, 'version': t.version, 'class': t.form_type.value,
         'matched': a.matched_phrases, 'missing_required': a.missing_required,
         'confidence': a.confidence} for t, a in matches]
    qualified = [(t, a) for t, a in matches if t.anchor_definitions and a.matched_phrases and a.all_required_matched]
    families = {t.form_type.value for t, _ in qualified}
    if len(families) > 1:
        return result('Unknown', 0.0, 'Conflicting form anchors',
                      'REVIEW_REQUIRED', sorted(families))
    if len(families) == 1:
        template, anchors = max(qualified, key=lambda item: item[1].confidence)
        return result(template.form_type.value, anchors.confidence,
                      'Existing required form anchors matched', 'PROCESSABLE', anchors.matched_phrases)
    if re.match(r'^(ATTACHMENT|SUPPORTING DOCUMENT)(\b|:)', text):
        return result('Attachment', 1.0, 'Explicit attachment heading',
                      'NON_PROCESSABLE', [re.match(r'^(ATTACHMENT|SUPPORTING DOCUMENT)', text).group()])

    # Document-level signals, not isolated clinical words found on claim forms.
    headings = [phrase for phrase in ('MEDICAL RECORD', 'PROGRESS NOTE', 'DISCHARGE SUMMARY',
                'OPERATIVE REPORT', 'CONSULTATION NOTE', 'HISTORY AND PHYSICAL')
                if re.search(r'\b' + phrase + r'S?\b', text)]
    sections = [phrase for phrase in ('CHIEF COMPLAINT', 'HISTORY OF PRESENT ILLNESS',
                'PHYSICAL EXAMINATION', 'ASSESSMENT AND PLAN') if phrase in text]
    salutation = re.search(r'\b(?:DEAR\s+(?:DR|DOCTOR|MR|MRS|MS)\b|TO WHOM IT MAY CONCERN\b)', text)
    closing = re.search(r'\b(?:SINCERELY|YOURS TRULY|YOURS FAITHFULLY|REGARDS)\b', text)
    medical = bool(headings) or len(sections) >= 2
    letter = salutation is not None and closing is not None
    evidence['document_signals'] = {'medical_headings': headings, 'clinical_sections': sections,
                                   'salutation': salutation.group() if salutation else None,
                                   'closing': closing.group() if closing else None}
    if medical and letter:
        return result('Unknown', 0.0, 'Conflicting medical-record and letter evidence',
                      'REVIEW_REQUIRED', headings + sections + [salutation.group(), closing.group()])
    if medical:
        return result('Medical Record', 1.0, 'Clinical document heading or multiple clinical sections',
                      'NON_PROCESSABLE', headings + sections)
    if letter:
        return result('Letter', 1.0, 'Correspondence salutation and closing both observed',
                      'NON_PROCESSABLE', [salutation.group(), closing.group()])
    return result('Unknown', 0.0, 'Insufficient evidence for any supported document class',
                  'REVIEW_REQUIRED', [])


def write_classification_report(pages, directory):
    directory = Path(directory)
    rows = [asdict(page) for page in pages]
    trace = {"type": "DocumentClassificationTrace", "version": 1,
             "classes": ['CMS1500', 'UB04', 'Attachment', 'Separator', 'Blank',
                         'Medical Record', 'Letter', 'Unknown'],
             "pages": [{"class": row['page_type'], **row} for row in rows]}
    (directory / 'classification_trace.json').write_text(json.dumps(trace, indent=2), encoding='utf-8')
    (directory / 'classification_report.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    # Render recorded decisions and evidence; never reclassify inside the dashboard.
    body = ''.join('<tr>' + ''.join('<td>' + escape(str(row[key])) + '</td>' for key in
                   ('page_number', 'class', 'confidence', 'reason', 'status')) +
                   '<td><details><summary>Evidence</summary><pre>' +
                   escape(json.dumps(row['evidence'], indent=2)) + '</pre></details></td></tr>'
                   for row in trace['pages'])
    html = (
        '<!doctype html><meta charset="utf-8"><title>Document classification</title>'
        '<style>body{font:16px system-ui;margin:32px}td,th{padding:12px;border:1px solid #ccc}'
        'pre{white-space:pre-wrap;max-width:600px}</style>'
        '<h1>Document classification</h1><p>Confidence expresses rule support, not calibrated probability. '
        'Unknown requires review. Document identity does not authorize registration.</p>'
        '<table><tr><th>Page</th><th>Class</th><th>Confidence</th><th>Reason</th><th>Status</th>'
        '<th>Evidence</th></tr>' + body + '</table>')
    (directory / 'classification_dashboard.html').write_text(html, encoding='utf-8')
    (directory / 'classification_report.html').write_text(html, encoding='utf-8')
