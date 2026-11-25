"""Recover review proposals for the frozen OCR blockers; no automatic release."""
import argparse
import copy
import csv
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from scripts import run_uat_all as batch
from workers.unstructured_extraction.uat_cases import decide_case

SOURCE = Path('runs/uat_25_cases_v6_20261125')
OUT = Path('runs/uat_vision_recovery_20261125')


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def identity_field_refs(records):
    field_refs = defaultdict(list)
    for r in records:
        doc = batch.read(SOURCE / 'cases' / r['id'] / 'final.json')
        if doc.get('effective_type') not in {'AADHAAR', 'PAN', 'IDENTITY_PROOF', 'DRIVING_LICENSE'}:
            continue
        for name, item in doc['decision']['extracted_fields'].items():
            if name not in {'patient_dob', 'identity_number', 'license_number'}:
                continue
            if item.get('raw_confidence', 0) >= .8 and item.get('evidence_reference') and not any(
                    reason.endswith(':'+name) for reason in doc['decision']['reason_codes']):
                field_refs[r['case_id']].append({**item, 'field_name': name, 'document_id': r['id'],
                                                'source_verified': True})
    return field_refs


def prepare():
    OUT.mkdir(exist_ok=False)
    records = copy.deepcopy(batch.read(SOURCE / 'inventory.json'))
    blockers = {r['document_id']: r for r in read_csv(SOURCE / 'review/category_b_root_causes_left.csv')
                if r['primary_b_root_cause'] == 'OCR miss'}
    prior_jobs = batch.read(SOURCE / 'affected_field_crop_jobs.json')
    prior_jobs += batch.read(Path('runs/uat_25_cases_v5_run_20261125/allowed_handwritten_name_jobs_v5.json'))
    field_refs = identity_field_refs(records)
    new_jobs, reuse = [], []
    for record in records:
        if record['id'] not in blockers:
            continue
        old = Path(record['directory']); directory = (OUT / 'cases' / record['id']).resolve()
        directory.mkdir(parents=True)
        for path in old.glob('*.json'):
            shutil.copyfile(path, directory / path.name)
        record['directory'] = str(directory)
        for name in ['local.json', 'final.json']:
            doc = batch.read(directory / name); doc['directory'] = str(directory); batch.write(directory / name, doc)
        record['apply_vision_recovery'] = True
        record['verified_field_sources'] = [r for r in field_refs[record['case_id']] if r['document_id'] != record['id']]
        record['vision_recovery_fields'] = sorted({r.split(':')[-1] for r in blockers[record['id']]['reasons'].split('; ')})
        record['vision_recovery_jobs'] = []
        for job in prior_jobs:
            if not job['id'].startswith(record['id'] + '/'):
                continue
            target = directory / Path(job['output']).name
            if not target.exists():
                continue
            recovered = {**job, 'output': str(target.relative_to(OUT.resolve())),
                         'localization_basis': 'REUSED_SOURCE_INSPECTED_FIELD_CROP'}
            record['vision_recovery_jobs'].append(recovered)
            reuse.append({'document_id': record['id'], 'job_id': job['id'], 'record': str(target), 'new_cloud_call': False})
        # The two OCR-blocked fields not included in the previous ten-document
        # cloud scope get one value-localized crop each. No whole-page retries.
        if record['id'] in {'3DYL021769/doc_004', '3KYL041813/doc_007'}:
            doc = batch.read(directory / 'final.json')
            field = 'tmt_interpretation' if record['declared_type'] == 'TMT' else 'ecg_interpretation'
            items = [i for i in doc['candidates'].get(field, []) if i.get('bounding_box') and not i.get('role_conflict')]
            if not items:
                raise ValueError('No source-localized crop for ' + record['id'])
            item = max(items, key=lambda i: i['raw_confidence']); asset = doc['assets'][item['page_number']-1]
            b = item['bounding_box']; margin = 20
            box = [max(0, (b['x0']-margin)/asset['width']), max(0, (b['y0']-margin)/asset['height']),
                   min(1, (b['x1']+margin)/asset['width']), min(1, (b['y1']+margin)/asset['height'])]
            job = {'id': record['id'] + '/vision_recovery/' + field, 'image': asset['path'], 'crop_fraction': box,
                   'fields': {field: batch.DESCRIPTIONS[field] + ' Transcribe the exact visible conclusion only. Do not diagnose from the waveform. Preserve spelling. Return null if unreadable.'},
                   'output': str((directory / 'llm_v7_vision_recovery.json').relative_to(OUT.resolve())),
                   'localization_basis': 'EXISTING_FIELD_VALUE_BOUNDING_BOX', 'purpose': 'OCR_BLOCKER_VISION_REVIEW_PROPOSAL'}
            record['vision_recovery_jobs'].append(job); new_jobs.append(job)
        print('Prepared OCR blocker:', record['id'], flush=True)
    assert len(blockers) == 12 and len(new_jobs) == 2
    batch.write(OUT / 'inventory.json', records)
    batch.write(OUT / 'new_crop_jobs.json', new_jobs)
    batch.write(OUT / 'reused_crop_records.json', reuse)
    batch.write(OUT / 'manifest.json', {'source': str(SOURCE.resolve()), 'ocr_blockers': sorted(blockers),
                'same_cases': 25, 'same_documents': 214, 'auto_accept_vision_only': False,
                'new_di_calls': 0, 'new_crop_calls_planned': len(new_jobs), 'reused_crop_records': len(reuse)})
    print('New cloud queue:', len(new_jobs), 'reused crops:', len(reuse), flush=True)


def finish():
    from PIL import Image
    records = batch.read(OUT / 'inventory.json')
    refs = identity_field_refs(records)
    for record in records:
        if record.get('apply_vision_recovery'):
            record['verified_field_sources'] = [r for r in refs[record['case_id']] if r['document_id'] != record['id']]
    batch.write(OUT / 'inventory.json', records)
    ledger = []
    for job in batch.read(OUT / 'new_crop_jobs.json'):
        result = batch.read(OUT / job['output'])
        if result['status'] not in {'SUCCESS', 'FAILED'}:
            raise ValueError('Provider jobs pending')
        ledger.append({k: result.get(k) for k in ['job_id', 'status', 'request_attempts', 'provider', 'seconds', 'usage']})
    all_docs = []; proposals = []; unresolved = []; value_changes = []
    for record in records:
        old = batch.read(SOURCE / 'cases' / record['id'] / 'final.json')
        doc = batch.evaluate(record, final=True) if record.get('apply_vision_recovery') else old
        all_docs.append(doc)
        before = {k: v['value'] for k, v in old['decision']['extracted_fields'].items()}
        after = {k: v['value'] for k, v in doc['decision']['extracted_fields'].items()}
        if before != after:
            value_changes.append({'document_id': record['id'], 'before': before, 'after': after})
        for item in doc['decision'].get('vision_only_review_proposals', []):
            crop_path = ''
            if item['bounding_box']:
                target = OUT / 'review_crops' / f'crop_{len(proposals)+1:03d}.png'
                target.parent.mkdir(exist_ok=True)
                with Image.open(item['source_image']) as image:
                    b = item['bounding_box']
                    crop = image.crop(tuple(round(b[k]) for k in ['x0','y0','x1','y1']))
                    crop.save(target)
                crop_path = str(target.resolve())
            proposals.append({'case_id': record['case_id'], 'document_id': record['id'], 'field': item['field_name'],
                'proposed_value': item['value'], 'review_status': item['review_status'],
                'validation_issues': '; '.join(item['validation_issues']),
                'source_page': item['page_number'], 'source_page_path': item['source_image'],
                'crop_fraction': str(item['crop_fraction']), 'evidence_reference': item['evidence_reference'],
                'review_crop_path': crop_path,
                'corroborating_documents': '; '.join(sorted({r['document_id'] for r in
                    item.get('corroborating_name_sources', []) + item.get('corroborating_field_sources', [])})),
                'model_confidence_not_accuracy': item['model_confidence'], 'ocr_confidence_available': False,
                'auto_accept_eligible': False, 'verify': '', 'correct': ''})
        if record.get('apply_vision_recovery'):
            unresolved.append({'document_id': record['id'], 'reasons': doc['decision']['reason_codes'],
                               'proposals': len(doc['decision'].get('vision_only_review_proposals', [])),
                               'complete': doc['decision']['extraction_stp_eligible']})
    summary = batch.report(records, OUT, final=True)
    bycase = defaultdict(list)
    for doc in all_docs:
        bycase[doc['case_id']].append(doc)
    cases = {case: decide_case(docs) for case, docs in bycase.items()}
    batch.write(OUT / 'case_decisions.json', cases)
    summary.update(vision_only_mode='REVIEW_PROPOSALS_ONLY', accuracy_measured=False,
        vision_proposals=len(proposals), proposal_outcomes=dict(Counter(p['review_status'] for p in proposals)),
        documents_with_proposals=len({p['document_id'] for p in proposals}),
        ocr_blockers_tested=12, unchanged_documents_reused=202,
        new_cloud_calls={'claude_crops': len(ledger), 'http_attempts': sum(r.get('request_attempts') or 1 for r in ledger),
                         'document_intelligence': 0, 'statuses': dict(Counter(r['status'] for r in ledger))},
        baseline_completed_documents=165, baseline_completed_cases=3,
        accepted_field_value_changes=len(value_changes), ocr_confidence_threshold=.8)
    batch.write(OUT / 'summary.json', summary)
    batch.write(OUT / 'cloud_call_log.json', ledger)
    batch.write(OUT / 'ocr_blocker_results.json', unresolved)
    batch.write(OUT / 'accepted_value_changes.json', value_changes)
    if proposals:
        with (OUT / 'vision_field_review.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(proposals[0])); writer.writeheader(); writer.writerows(proposals)
    print(summary, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['prepare', 'final'], required=True)
    args = parser.parse_args()
    prepare() if args.stage == 'prepare' else finish()
