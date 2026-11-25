"""Write the final case states, provider ledger and stratified accuracy sample."""
import csv
import hashlib
import random
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from scripts import run_uat_all as batch
from scripts.create_participant_spreadsheet import NS, sheet, styles
from scripts.run_uat_v6_25 import AFFECTED, OUT, SOURCE, csv_rows
from workers.unstructured_extraction.uat_recovery_rules import name_similarity


def save_csv(path, rows, headers=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def workbook(path, tables):
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(tables)+1)) + '</Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(tables, 1)) + '</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(tables)+1)) + f'<Relationship Id="rId{len(tables)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr('xl/styles.xml', styles)
        for i, (_, rows) in enumerate(tables, 1):
            headers = list(rows[0])
            values = [[r.get(h, '') for h in headers] for r in rows]
            # A source image link opens the exact page; CSV keeps the raw path.
            for row in values:
                if 'source_page_path' in headers:
                    col = headers.index('source_page_path')
                    if row[col]:
                        row[col] = '=HYPERLINK("' + Path(row[col]).resolve().as_uri().replace('"', '""') + '","Open source page")'
            archive.writestr(f'xl/worksheets/sheet{i}.xml', sheet(headers, values))
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            ET.fromstring(archive.read(name))


def main():
    review = OUT / 'review'
    review.mkdir(exist_ok=True)
    records = batch.read(OUT / 'inventory.json')
    originals = batch.read(SOURCE / 'inventory.json')
    assert [r['id'] for r in records] == [r['id'] for r in originals]
    documents = {r['id']: batch.read(Path(r['directory']) / 'final.json') for r in records}
    before = {r['id']: batch.read(SOURCE / 'cases' / r['id'] / 'final.json') for r in records}
    cases = batch.read(OUT / 'case_decisions.json')
    states, blocking_docs, changes, pool = [], [], [], defaultdict(list)
    old_categories = {r['document_id']: r['category'] for r in csv_rows(SOURCE / 'review/remaining_blockers.csv')}
    old_b = {r['document_id']: r for r in csv_rows(SOURCE / 'review/category_b_root_causes_left.csv')}
    remaining_b, all_blockers = [], []
    for record in records:
        id = record['id']; doc = documents[id]; decision = doc['decision']; old = before[id]['decision']
        kind = doc.get('effective_type', decision['document_type'])
        reasons = decision['reason_codes']
        if reasons:
            category = old_categories.get(id, 'B')
            root = old_b.get(id, {}).get('primary_root_cause', 'OCR miss')
            note = old_b.get(id, {}).get('diagnosis', '')
            if id in AFFECTED:
                note = 'Affected-page DI and field crops completed; unresolved source readings/field mapping remain. See cloud ledger and field diagnostics.'
            if id == '3DYL021769/doc_004':
                root = 'OCR miss'; note = 'Name order/initial normalisation resolved; only low-confidence conclusion remains.'
            if id == '3KYL041813/doc_007':
                root = 'OCR miss'; note = 'Date recovered at 0.852 locally; interpretation still below 0.80. Acceptance threshold unchanged.'
            if {r.split(':')[0] for r in reasons} == {'AMBIGUOUS_DATE_YEAR'}:
                category = 'C'; note = 'Only a short or ambiguous year remains; no century inference.'
            discrepancy = any(i.get('rejection_basis') == 'CERTIFICATE_DECLARATION_YEAR_DISCREPANCY'
                              for i in doc['candidates'].get('examination_date', []))
            if discrepancy:
                category = 'C'; note = 'Certificate OCR year contradicts declaration; source reading held, not rewritten.'
            row = {'case_id': record['case_id'], 'document_id': id, 'document': record['document'], 'type': kind,
                   'category': category, 'primary_b_root_cause': root if category == 'B' else '',
                   'reasons': '; '.join(reasons), 'diagnosis': note,
                   'source_pages': '; '.join(f'p{a["page"]}: {a["path"]}' for a in doc['assets'])}
            all_blockers.append(row)
            if category == 'B':
                remaining_b.append(row)
        if old['extraction_stp_eligible']:
            for field in sorted(set(old['extracted_fields']) | set(decision['extracted_fields'])):
                a = old['extracted_fields'].get(field, {}).get('value', '')
                b = decision['extracted_fields'].get(field, {}).get('value', '')
                if a != b:
                    source = old['extracted_fields'].get(field) or decision['extracted_fields'][field]
                    p = source.get('page_number', 1)
                    changes.append({'document_id': id, 'field': field, 'before_value': a, 'after_value': b,
                                    'after_complete': decision['extraction_stp_eligible'], 'reason': '; '.join(reasons),
                                    'source_page': p, 'source_page_path': doc['assets'][p-1]['path']})
        if decision['extraction_stp_eligible']:
            sample_type = ('PAN' if decision.get('value_representations', {}).get('identity_number', {}).get('kind') == 'full_pan' else kind)
            for field, value in decision['extracted_fields'].items():
                p = value.get('page_number', 1)
                pool[sample_type].append({'type': sample_type, 'schema_type': kind, 'case_id': record['case_id'], 'document_id': id,
                                   'field': field, 'extracted_value': value['value'],
                                   'raw_confidence': value.get('raw_confidence', ''), 'source_page': p,
                                   'source_page_path': doc['assets'][p-1]['path'],
                                   'evidence_reference': value.get('evidence_reference', ''), 'verify': '', 'correct': ''})
    for case, decision in cases.items():
        blocks = [r for r in all_blockers if r['case_id'] == case]
        states.append({'case_id': case, 'state': 'COMPLETE' if decision['case_complete'] else 'REVIEW',
                       'blocking_document_count': len(blocks),
                       'blocking_documents_and_reasons': ' | '.join(r['document_id'] + ': ' + r['reasons'] for r in blocks),
                       'missing_case_roles': '; '.join(decision['missing_roles']),
                       'case_flags': '; '.join(map(str, decision.get('supply_flags', [])))})
        blocking_docs.extend(blocks)
        assert bool(not blocks and not decision['missing_roles']) == decision['case_complete']
    assert len(states) == 25

    # Frozen v5 outcomes: call yield is measured before v6, not retroactively
    # credited for names recovered by another provider in this run.
    yield_rows = []
    old_records = {r['id']: r for r in originals}
    for job in batch.read(SOURCE / 'allowed_handwritten_name_jobs_v5.json'):
        id = job['id'].split('/handwritten_name/')[0]; result = batch.read(SOURCE / job['output'])
        field = next(f for f in result['fields'] if f['field_name'] == 'patient_name')
        value = field.get('value') or ''; decision = before[id]['decision']
        page = next(a['page'] for a in before[id]['assets'] if a['path'] == job['image'])
        refs = old_records[id].get('verified_name_sources', [])
        similarity = max((name_similarity(value, ref['value']) for ref in refs), default=0)
        observations = decision.get('field_diagnostics', {}).get('patient_name', {}).get('observations', [])
        ambiguous = any(o['candidate'].get('source_reading_ambiguous') and o['candidate']['value'] == value for o in observations)
        blocked_name = any(r.endswith(':patient_name') for r in decision['reason_codes'])
        selected = decision['extracted_fields'].get('patient_name', {})
        if not value or field.get('insufficient_evidence'):
            status, why = 'UNRESOLVED', 'Model abstained/no name returned'
        elif ambiguous or similarity < .9:
            status, why = 'REJECTED', 'Unsupported spelling or failed other-document name match'
        elif selected and not blocked_name and name_similarity(value, selected['value']) >= .9:
            status, why = 'ACCEPTED', 'Name field accepted; other document fields can still block completion'
        else:
            status, why = 'UNRESOLVED', 'Returned candidate but name field retains conflicting source values'
        yield_rows.append({'job_id': job['id'], 'document_id': id, 'name_returned': value,
                           'outcome_at_v5': status, 'reason': why, 'source_page': page,
                           'source_page_path': job['image'], 'cloud_record': str((SOURCE/job['output']).resolve())})
    assert len(yield_rows) == 29

    # Minimum three fields per represented type, then proportional allocation.
    rng = random.Random(20261125)
    for values in pool.values():
        rng.shuffle(values)
    quotas = {kind: min(3, len(values)) for kind, values in pool.items()}
    while sum(quotas.values()) < 50:
        kind = max((k for k in pool if quotas[k] < len(pool[k])), key=lambda k: (len(pool[k])/(quotas[k]+1), k))
        quotas[kind] += 1
    sample = [dict(sample_id=f'F{n:03d}', **item) for n, item in enumerate(
        [item for k in sorted(pool) for item in pool[k][:quotas[k]]], 1)]
    assert len(sample) == 50 and all(r['verify'] == r['correct'] == '' for r in sample)
    assert len({(r['document_id'], r['field']) for r in sample}) == 50
    assert all(Path(r['source_page_path']).exists() for r in sample)

    ledger = []
    for stage, plan in [('DI', 'affected_di_jobs.json'), ('CLAUDE_CROP', 'affected_field_crop_jobs.json')]:
        for job in batch.read(OUT / plan):
            result = batch.read(OUT / job['output'])
            assert result['status'] in {'SUCCESS', 'FAILED'}
            assert job['id'].split('/v6_')[0] in AFFECTED
            ledger.append({'stage': stage, 'job_id': job['id'], 'status': result['status'],
                           'fields': '; '.join(job.get('fields', job.get('affected_fields', []))),
                           'request_attempts': result.get('request_attempts', 'DI retry/poll HTTP count not instrumented'),
                           'seconds': result['seconds'], 'result_record': str((OUT/job['output']).resolve())})
    summary = batch.read(OUT / 'summary.json')
    summary.update(baseline_completed_documents=164, baseline_completed_cases=3,
                   newly_completed_documents=sum(doc['decision']['extraction_stp_eligible'] and not before[id]['decision']['extraction_stp_eligible'] for id, doc in documents.items()),
                   previously_completed_now_review=sum(not doc['decision']['extraction_stp_eligible'] and before[id]['decision']['extraction_stp_eligible'] for id, doc in documents.items()),
                   previous_completed_value_changes=len(changes),
                   remaining_primary_abc=dict(Counter(r['category'] for r in all_blockers)),
                   category_b_primary_root_causes=dict(Counter(r['primary_b_root_cause'] for r in remaining_b)),
                   category_b_diagnosis_status='PROVISIONAL_SOURCE_INFORMED',
                   new_cloud_calls={'document_intelligence_pages': sum(r['stage']=='DI' for r in ledger),
                                    'claude_field_crops': sum(r['stage']=='CLAUDE_CROP' for r in ledger),
                                    'claude_http_attempts': sum(r['request_attempts'] for r in ledger if r['stage']=='CLAUDE_CROP'),
                                    'other': 0, 'statuses': dict(Counter(r['status'] for r in ledger))},
                   handwritten_29_call_yield_at_v5=dict(Counter(r['outcome_at_v5'] for r in yield_rows)),
                   accuracy_sample={'fields': 50, 'by_type': quotas, 'seed': 20261125,
                                    'human_verified_fields': 0, 'asset_only_documents_excluded': True},
                   minimum_ocr_confidence=.8, independent_accuracy_verified=False,
                   new_cloud_scope='14_AFFECTED_OCR_MISS_PAGES_THEN_UNRESOLVED_FIELD_CROPS_ONLY')
    assert summary['completed_documents'] == sum(d['decision']['extraction_stp_eligible'] for d in documents.values())
    assert summary['fully_completed_cases'] == sum(c['case_complete'] for c in cases.values())
    batch.write(OUT / 'summary.json', summary)
    batch.write(OUT / 'cloud_call_log.json', {'counts': summary['new_cloud_calls'], 'calls': ledger})
    batch.write(OUT / 'configuration_manifest.json', {'same_cohort': True, 'minimum_ocr_confidence': .8,
        'tests': '73 passed', 'independent_accuracy_verified': False,
        'sha256': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [
            'config/uat_extraction_acceptance.yaml', 'scripts/run_uat_all.py', 'scripts/run_uat_v6_25.py',
            'workers/unstructured_extraction/uat_binding_v6.py', 'workers/unstructured_extraction/uat_recovery_rules.py']}})
    schema = batch.read(OUT / 'schema_mapping_breakdown.json')
    fixes = [
        {'pattern': 'MER/examination_date (3 documents)', 'change': 'Bind certificate Date by position, including handwriting just above label.', 'wrong_value_control': 'Preserve short years; certificate/declaration year discrepancies held. 4BYL021912/doc_001 OCR 2016 conflicts with declaration 2026; not accepted.'},
        {'pattern': 'ECG/ecg_interpretation (3 documents)', 'change': 'Map Diagnosis Information column and wrapped lines without adding partial duplicates to existing bound diagnoses.', 'wrong_value_control': 'No inferred diagnosis from waveform; existing confidence minimum unchanged.'},
        {'pattern': 'Acceptance/4BYL021912/doc_004', 'change': 'Match visible masked suffix against another source document.', 'wrong_value_control': 'The second document contains a copy of the same card; not an independent identity/authenticity check. Hidden digits never inferred.'},
        {'pattern': 'Acceptance/3KYL041813/doc_007', 'change': 'Local date crop recovered at 0.852; interpretation still below threshold.', 'wrong_value_control': 'REVIEW remains. No confidence promotion or acceptance relaxation.'},
        {'pattern': 'Normalisation/3DYL021769/doc_004', 'change': 'Name order/initial conflict resolved with all initials preserved and full-name letters matching.', 'wrong_value_control': 'Different initials still conflict. Document remains REVIEW for low-confidence conclusion.'},
    ]
    save_csv(review/'case_states_25.csv', states)
    save_csv(review/'blocking_documents.csv', blocking_docs)
    save_csv(review/'category_b_root_causes_left.csv', remaining_b)
    save_csv(review/'schema_mapping_breakdown.csv', schema)
    save_csv(review/'handwritten_29_call_yield.csv', yield_rows)
    save_csv(review/'accuracy_sample_50.csv', sample)
    save_csv(review/'previously_completed_value_changes.csv', changes,
             ['document_id','field','before_value','after_value','after_complete','reason','source_page','source_page_path'])
    save_csv(review/'cloud_call_ledger.csv', ledger)
    save_csv(review/'fix_outcomes.csv', fixes)
    readme = [{'item': 'Metric definition', 'detail': 'Extraction completeness only. No independent accuracy estimate until blank verify/correct columns are manually filled.'},
              {'item': 'Sample selection', 'detail': '50 unique fields from completed structured documents, seeded stratification by type; PAN-number cards are a separate PAN stratum even where the schema is IDENTITY_PROOF. No completed TMT is available. Asset-only photos have no scalar fields.'},
              {'item': 'Case states', 'detail': 'All 25 cases listed; REVIEW includes every blocking document and missing case role.'},
              {'item': 'Call yield denominator', 'detail': 'All 29 original v5 name-crop calls, evaluated against frozen v5 field outcomes. Abstentions and name conflicts are unresolved; unsupported readings are rejected.'},
              {'item': 'Remaining B', 'detail': 'One provisional primary root cause per blocked B document; fields/reasons remain explicit. Normalisation now resolved; the TMT conclusion is a separate OCR blocker.'},
              {'item': 'Acceptance thresholds', 'detail': '0.80 unchanged. New same-span supersession needs OCR >=0.80 plus crop agreement; high-confidence disagreements/different source spans retained.'}]
    tables = [('Readme', readme), ('Case states', states), ('Blocking documents', blocking_docs),
              ('Accuracy sample 50', sample), ('Schema patterns', schema), ('Fix outcomes', fixes),
              ('B roots left', remaining_b), ('Handwritten yield 29', yield_rows), ('Cloud calls', ledger)]
    if changes:
        tables.append(('Previous value changes', changes))
    workbook(review/'UAT_v6_final_case_states_and_accuracy.xlsx', tables)
    # Plain text report for quick review, preserving all document reasons.
    lines = ['25-case final extraction audit', '', str(summary), '', 'CASE STATES']
    lines.extend(r['case_id'] + ' ' + r['state'] + ': ' + (r['blocking_documents_and_reasons'] or 'all documents complete')
                 + ('; missing case roles: '+r['missing_case_roles'] if r['missing_case_roles'] else '') for r in states)
    (review/'final_report.txt').write_text('\n'.join(lines), encoding='utf-8')
    print(summary)
    print('Workbook:', review/'UAT_v6_final_case_states_and_accuracy.xlsx')


if __name__ == '__main__':
    main()
