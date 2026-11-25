"""Re-run the fixed 25-case cohort with a narrowly allowlisted cloud queue."""
import argparse
from collections import defaultdict
from pathlib import Path

from packages.layout_intelligence.engine import BundleDResult
from packages.ocr.text_extraction import TextLine
from scripts import run_uat_all as batch
from scripts.test_uat_subset import prepare as clone_subset
from workers.unstructured_extraction.uat_cases import decide_case
from workers.unstructured_extraction.uat_recovery_rules import masked_candidates, name_similarity
from workers.unstructured_extraction.uat_validation import valid_scalar

MEDICAL = {'PATH', 'MER', 'ECG', 'TMT'}


def pages_for(doc):
    layouts = []
    for asset, path in zip(doc['assets'], doc['layouts'], strict=True):
        di = Path(doc['directory']) / f"di_page_{asset['page']:03d}.json"
        lines = batch.di_lines(batch.read(di), asset['width'], asset['height']) if di.exists() else []
        layouts.append(batch.SERVICE.extract_page(lines, page_number=asset['page'], width=asset['width'],
            height=asset['height'], engine='azure_document_intelligence_read', document_family=doc['declared_type'])
            if lines else BundleDResult.model_validate_json(Path(path).read_text(encoding='utf-8')))
    return layouts


def prepare(source, output):
    clone_subset(source, output, 25)
    output = Path(output).resolve()
    records = batch.read(output / 'inventory.json')
    identities = defaultdict(list)
    masks = defaultdict(list)
    for index, record in enumerate(records, 1):
        directory = Path(record['directory'])
        previous = batch.read(directory / 'final.json')
        local = batch.read(directory / 'local.json')
        layouts, paths = [], []
        for asset in local['assets']:
            raw = batch.read(Path(asset['path']).with_suffix('.json'))
            layout = batch.SERVICE.extract_page([TextLine(**line) for line in raw['ocr_lines']],
                page_number=asset['page'], width=asset['width'], height=asset['height'],
                engine='tesseract_psm_11', document_family=record['declared_type'])
            path = directory / f"layout_v4_{asset['page']:03d}.json"
            path.write_text(layout.model_dump_json(), encoding='utf-8')
            layouts.append(layout)
            paths.append(str(path))
        fields = batch.SERVICE.complete(record['sha256'], layouts, document_family='UAT_' + record['declared_type'], type_verified=True)
        local.update(layouts=paths, candidates=fields['extracted_candidates'], stage='LOCAL')
        local['decision'] = batch.ACCEPT.decide(record['declared_type'], layouts, expected_pages=record['pages'],
            assets=local['assets'], candidates=local['candidates'])
        batch.write(directory / 'local.json', local)
        record['apply_recovery_v4'] = True
        if record['declared_type'] in {'AADHAAR', 'PAN', 'IDENTITY_PROOF'}:
            for name in {item['value'] for item in previous['candidates'].get('patient_name', [])
                         if item.get('raw_confidence', 0) >= .8 and valid_scalar('patient_name', item['value'])
                         and item.get('field_association') in {'DIRECT_LABEL', 'BOUNDED_BELOW_LABEL', 'LLM_VALUE_LOCATED_IN_OCR'}}:
                identities[record['case_id']].append({'name': name, 'document_id': record['id'],
                    'accepted_identity_document': previous['decision']['extraction_stp_eligible']})
        if record['declared_type'] in {'AADHAAR', 'IDENTITY_PROOF'}:
            record['masked_candidates'] = masked_candidates(local['assets'], pages_for(local))
            masks[record['case_id']].extend((record['id'], item['suffix']) for item in record['masked_candidates'])
        if index % 25 == 0:
            print('Prepared', index, '/', len(records), flush=True)
    context = {}
    for case, values in identities.items():
        groups = []
        for value in values:
            group = next((g for g in groups if all(name_similarity(value['name'], item['name']) >= .90 for item in g)), None)
            if group is None:
                groups.append([value])
            else:
                group.append(value)
        groups.sort(key=lambda g: len({item['document_id'] for item in g}), reverse=True)
        support=[len({item['document_id'] for item in group}) for group in groups]
        consensus=len(groups)==1 or (support[0]>=2 and support[0]>support[1])
        context[case] = {'names': sorted({item['name'] for item in groups[0]}) if consensus else [],
                         'source_groups': groups, 'status': 'CORROBORATED_IDENTITY_SOURCE' if consensus else 'CONFLICTING_IDENTITY_NAMES'}
    for record in records:
        record['case_known_names'] = context.get(record['case_id'], {}).get('names', [])
        record['case_aadhaar_suffixes'] = sorted({suffix for doc, suffix in masks[record['case_id']] if doc != record['id']})
    batch.write(output / 'case_name_context.json', context)
    batch.write(output / 'inventory.json', records)
    di_jobs = []
    for record in records:
        if record['declared_type'] != 'TMT':
            continue
        local = batch.read(Path(record['directory']) / 'local.json')
        for asset in local['assets']:
            target = Path(record['directory']) / f"di_page_{asset['page']:03d}.json"
            if not target.exists():
                di_jobs.append({'id': record['id'] + '/p' + str(asset['page']), 'image': asset['path'],
                                'output': str(target.relative_to(output)), 'document_type': 'TMT'})
    batch.write(output / 'allowed_tmt_di_jobs.json', di_jobs)
    batch.write(output / 'allowed_handwritten_name_jobs.json', [])
    print('New TMT DI pages:', len(di_jobs), flush=True)


def reconcile(output, prepare_handwriting=False):
    output = Path(output).resolve()
    records = batch.read(output / 'inventory.json')
    documents = []
    jobs = []
    for index, record in enumerate(records, 1):
        doc = batch.evaluate(record, final=True)
        documents.append(doc)
        if prepare_handwriting and record['declared_type'] in {'MER','ECG'} and record['case_known_names'] and any(
            reason.endswith(':patient_name') for reason in doc['decision']['reason_codes']):
            # A known-name witness is required; only names, never whole-document fields.
            for asset in doc['assets']:
                if record['declared_type']=='MER' and asset['page']>2:
                    continue
                # Label on MER can follow an attached cover. ECG names can
                # be handwritten beside traces or in a footer margin.
                regions = [('header', [.01, .01, .99, .48])]
                if record['declared_type'] == 'ECG':
                    regions += [('footer', [.01, .55, .99, .99])]
                for role, box in regions:
                    jobs.append({'id': record['id'] + '/handwritten_name/p' + str(asset['page']) + '/' + role,
                        'image': asset['path'], 'crop_fraction': box,
                        'fields': {'patient_name': 'Read the exact handwritten patient name, if present. Do not return printed text, doctors, relatives, signatures, or form labels. Null if no handwritten patient name is visible.'},
                        'output': str((Path(record['directory']) / f"llm_p{asset['page']:03d}_handwritten_name_{role}.json").relative_to(output)),
                        'purpose': 'HANDWRITTEN_PATIENT_NAME_ONLY'})
        if index % 25 == 0:
            print('Reconciled', index, '/', len(records), flush=True)
    if prepare_handwriting:
        batch.write(output / 'allowed_handwritten_name_jobs.json', jobs)
        print('Handwritten name crops:', len(jobs), flush=True)
    summary = batch.report(records, output, final=True)
    cases = defaultdict(list)
    for doc in documents:
        cases[doc['case_id']].append(doc)
    batch.write(output / 'case_decisions.json', {case: decide_case(docs) for case, docs in cases.items()})
    summary['baseline_completed_documents'] = batch.read(output / 'baseline_summary.json')['completed_documents']
    summary['new_cloud_scope'] = 'TMT_DOCUMENT_INTELLIGENCE_AND_HANDWRITTEN_NAME_CROPS_ONLY'
    summary['validation_status'] = 'DEVELOPMENT_CASE_TEST_ACCURACY_UNMEASURED'
    batch.write(output / 'summary.json', summary)
    print(summary, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runs/uat_25_cases_v3_20261124'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=['prepare', 'names', 'final'], required=True)
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare(args.source, args.output)
    else:
        reconcile(args.output, prepare_handwriting=args.stage == 'names')
