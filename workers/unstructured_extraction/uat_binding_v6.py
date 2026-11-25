"""Source geometry recovery; no confidence promotion or inferred date century."""
import re

from workers.unstructured_extraction.uat_binding_v5 import source_rows, witness
from workers.unstructured_extraction.uat_values import DATE_PATTERN, date_value


def span(tokens, association):
    if not tokens:
        return None
    return {'value': ' '.join(t.text for t in tokens), 'raw_confidence': min(t.confidence or 0 for t in tokens),
            'page_number': tokens[0].page_number, 'field_association': association,
            'evidence_reference': f'page:{tokens[0].page_number}:{association}:{int(tokens[0].bbox.x0)}:{int(tokens[0].bbox.y0)}',
            'bounding_box': {'x0': min(t.bbox.x0 for t in tokens), 'y0': min(t.bbox.y0 for t in tokens),
                             'x1': max(t.bbox.x1 for t in tokens), 'y1': max(t.bbox.y1 for t in tokens)}}


def recover(kind, pages, candidates):
    # Two new observations (DI words + a field-only model reading) can resolve
    # an obsolete OCR reading at the SAME location, not a different source date.
    for field in ['report_date', 'patient_dob', 'examination_date']:
        items = candidates.get(field, [])
        fresh = [i for i in items if 'llm_v6_' in i.get('mapping_record', '')
                 and i.get('raw_confidence', 0) >= .8 and not i.get('role_conflict')]
        for item in items:
            a = item.get('bounding_box', {})
            if not a:
                continue
            for new in fresh:
                b = new.get('bounding_box', {})
                if not b or item.get('page_number') != new.get('page_number'):
                    continue
                av, bv = date_value(item['value']), date_value(new['value'])
                if not av['canonical_value'] or not bv['canonical_value'] or av['canonical_value'] == bv['canonical_value']:
                    continue
                overlap = max(0, min(a['x1'], b['x1']) - max(a['x0'], b['x0'])) * max(0, min(a['y1'], b['y1']) - max(a['y0'], b['y0']))
                area = min((a['x1']-a['x0'])*(a['y1']-a['y0']), (b['x1']-b['x0'])*(b['y1']-b['y0']))
                if area > 0 and overlap / area >= .6 and item['raw_confidence'] < .8:
                    item.update(role_conflict=True, rejection_basis='LOW_CONFIDENCE_SAME_SPAN_REOCR_AND_CROP_AGREE',
                                replacement_evidence=new['mapping_record'], replacement_value=new['value'])
    for page in pages:
        rows = source_rows(page)
        text = ' '.join(r['text'] for r in rows)
        if kind == 'MER' and re.search(r'CERTIFICATE', text, re.IGNORECASE):
            for row in rows:
                label = re.search(r'^\s*Date\s*[:.]?', row['text'], re.IGNORECASE)
                if not label:
                    continue
                anchor = witness(label.group(), row, 'CERTIFICATE_DATE_POSITION')
                if not anchor:
                    continue
                box = anchor['bounding_box']; height = max(1, box['y1'] - box['y0'])
                # Certificate handwriting may lie just above the printed rule.
                for near in rows:
                    for match in re.finditer(DATE_PATTERN, near['text']):
                        item = witness(match.group(), near, 'CERTIFICATE_DATE_POSITION')
                        b = item['bounding_box']
                        if abs((b['y0'] + b['y1'] - box['y0'] - box['y1']) / 2) <= 1.8 * height and box['x1'] <= b['x0'] <= box['x1'] + 12 * height:
                            candidates.setdefault('examination_date', []).append(item)
        if kind == 'ECG' and not any(i.get('raw_confidence', 0) >= .8 and not i.get('role_conflict')
                                     for i in candidates.get('ecg_interpretation', [])):
            for row in rows:
                label = re.search(r'Diagnosis\s+Information\s*:', row['text'], re.IGNORECASE)
                if not label:
                    continue
                anchor = witness(label.group(), row, 'DOCUMENT_DATE_POSITION')
                b = anchor['bounding_box']; height = max(1, b['y1'] - b['y0'])
                tokens = [t for near in rows for t in near['tokens']
                          if b['x0'] - height <= t.bbox.x0 <= b['x0'] + 18 * height
                          and b['y1'] <= (t.bbox.y0 + t.bbox.y1) / 2 <= b['y1'] + 4.5 * height]
                tokens.sort(key=lambda t: (round(t.bbox.y0 / height), t.bbox.x0))
                item = span(tokens, 'SCHEMA_DIAGNOSIS_COLUMN')
                if item and re.search(r'sinus|rhythm|block|normal|abnormal', item['value'], re.IGNORECASE):
                    candidates.setdefault('ecg_interpretation', []).append(item)
        if kind == 'TMT':
            # Exact printed conclusion can wrap around an overlaid doctor stamp.
            for i, row in enumerate(rows):
                match = re.search(r'\b(?:TEST\s+)?NEGATIVE\s+FOR\s+INDUC(?:A|I)BLE\b', row['text'], re.IGNORECASE)
                if not match:
                    continue
                first = witness(match.group(), row, 'SCHEMA_DIAGNOSIS_COLUMN')
                for near in rows[i:i+4]:
                    end = re.search(r'\bISCH(?:A?E|E)MIA\b', near['text'], re.IGNORECASE)
                    if not end:
                        continue
                    last = witness(end.group(), near, 'SCHEMA_DIAGNOSIS_COLUMN')
                    if near is row:
                        item = witness(row['text'][match.start():end.end()], row, 'SCHEMA_DIAGNOSIS_COLUMN')
                        candidates.setdefault('tmt_interpretation', []).append(item)
                        break
                    if last['bounding_box']['x0'] > first['bounding_box']['x1'] + 50:
                        continue
                    item = dict(first)
                    item['value'] = first['value'] + ' ' + last['value']
                    item['raw_confidence'] = min(first['raw_confidence'], last['raw_confidence'])
                    item['bounding_box'] = {k: (min if k in {'x0', 'y0'} else max)(first['bounding_box'][k], last['bounding_box'][k]) for k in first['bounding_box']}
                    candidates.setdefault('tmt_interpretation', []).append(item)
                    break
    # A recovered certificate year that contradicts the form's declaration is
    # a source-reading discrepancy, not an excuse to silently change its year.
    if kind == 'MER':
        declarations = []
        for page in pages:
            rows = source_rows(page)
            labels = [r for r in rows if re.search(r'declaration\s+by', r['text'], re.IGNORECASE)]
            if not labels:
                continue
            for row in rows:
                if row['cy'] > labels[0]['cy']:
                    declarations.extend(date_value(m.group()) for m in re.finditer(DATE_PATTERN, row['text']))
        years = {d['canonical_value'][:4] for d in declarations if d['canonical_value'] and not d['year_ambiguous']}
        for item in candidates.get('examination_date', []):
            parsed = date_value(item['value'])
            if (item.get('field_association') == 'CERTIFICATE_DATE_POSITION' and years
                    and parsed['canonical_value'] and parsed['canonical_value'][:4] not in years):
                item.update(role_conflict=True, rejection_basis='CERTIFICATE_DECLARATION_YEAR_DISCREPANCY')
    # Sliding name windows must not create conflicting truncated initials.
    names = candidates.get('patient_name', [])
    for item in names:
        # The PR interval label must not displace the complete patient name.
        if (kind == 'ECG' and re.search(r'\sPR\s*$', item['value'])
                and any(re.search(r'\bPR\s*[:(].*\bms\b', row['text'], re.IGNORECASE)
                        for page in pages for row in source_rows(page))):
            item.update(role_conflict=True, rejection_basis='ECG_PR_INTERVAL_LABEL_IN_NAME')
        if re.search(r'stress test|graded exercise|treadmill', item['value'], re.IGNORECASE):
            item.update(role_conflict=True, rejection_basis='TEST_TITLE_IS_NOT_PATIENT_NAME')
    for item in names:
        value = re.sub(r'[^a-z]', '', item['value'].casefold())
        if item.get('field_association') != 'CASE_NAME_SOURCE_MATCH':
            continue
        for other in names:
            full = re.sub(r'[^a-z]', '', other['value'].casefold())
            a, b = item.get('bounding_box', {}), other.get('bounding_box', {})
            if (not other.get('role_conflict') and full.startswith(value) and len(full) > len(value)
                    and item.get('page_number') == other.get('page_number') and a and b
                    and b['x0'] <= a['x0'] + 2 and b['x1'] >= a['x1'] - 2
                    and abs(a['y0'] - b['y0']) < max(2, a['y1'] - a['y0'])):
                item.update(role_conflict=True, rejection_basis='SOURCE_NAME_WINDOW_TRUNCATED')
                break
    return candidates
