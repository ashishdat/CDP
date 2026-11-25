"""Rebuild UAT decisions from immutable recorded OCR and provider evidence."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from packages.ocr.text_extraction import TextLine
from scripts import run_uat_all as batch
from workers.unstructured_extraction.uat_cases import decide_case
from workers.unstructured_extraction.uat_localization import field_region


def replay(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    records = batch.read(source / 'inventory.json')
    verified = set()
    review = []
    recovery = []
    cases = {}
    for index, record in enumerate(records, 1):
        old_dir = Path(record['directory'])
        local = batch.read(old_dir / 'local.json')
        directory = output / 'cases' / record['id']
        directory.mkdir(parents=True)
        kind = batch.nominate_type(record['document'], record['manifest_type'], batch.load_policy())
        record.update(directory=str(directory), declared_type=kind)
        assets = local['assets']
        layouts, paths = [], []
        for asset in assets:
            image = Path(asset['path'])
            if image not in verified:
                if hashlib.sha256(image.read_bytes()).hexdigest() != asset['sha256']:
                    raise ValueError(f'Asset checksum mismatch: {image}')
                verified.add(image)
            raw = batch.read(image.with_suffix('.json'))
            lines = [TextLine(**line) for line in raw['ocr_lines']]
            layout = batch.SERVICE.extract_page(lines, page_number=asset['page'],
                width=asset['width'], height=asset['height'], engine='tesseract_psm_11', document_family=kind)
            path = directory / f"layout_{asset['page']:03d}.json"
            path.write_text(layout.model_dump_json(), encoding='utf-8')
            layouts.append(layout)
            paths.append(str(path))
        source_file = Path(record['source'])
        if hashlib.sha256(source_file.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Document checksum mismatch')
        fields = batch.SERVICE.complete(record['sha256'], layouts, document_family='UAT_' + kind, type_verified=True)
        candidates = fields['extracted_candidates']
        decision = batch.ACCEPT.decide(kind, layouts, expected_pages=record['pages'], assets=assets, candidates=candidates)
        batch.write(directory / 'local.json', dict(record, assets=assets, layouts=paths,
            candidates=candidates, decision=decision, effective_type=kind, stage='LOCAL'))
        provider_dirs = [old_dir]
        if local.get('seed_from'):
            provider_dirs.insert(0, Path(local['seed_from']).parent)
        for provider_dir in provider_dirs:
            for pattern in ['di_page_*.json', 'llm_*.json']:
                for path in provider_dir.glob(pattern):
                    payload = batch.read(path)
                    if payload.get('source_image'):
                        image_hash = hashlib.sha256(Path(payload['source_image']).read_bytes()).hexdigest()
                        matches = [a for a in assets if a['sha256'] == image_hash]
                        if not matches:
                            raise ValueError(f'Provider image does not match source assets: {path}')
                        payload['source_image'] = matches[0]['path']
                    batch.write(directory / path.name, payload)
        final = batch.evaluate(record, final=True)
        if not final['decision']['extraction_stp_eligible']:
            gaps = {reason.split(':', 1)[1] for reason in final['decision']['reason_codes'] if ':' in reason}
            for field in gaps:
                if field not in batch.DESCRIPTIONS:
                    continue
                aliases = batch.SERVICE.layout.labels.fields.get(field, {}).get('aliases', [])
                for asset, layout in zip(assets, layouts, strict=True):
                    box = field_region(layout, aliases, asset['width'], asset['height'])
                    if box:
                        recovery.append({'id': record['id'] + '/' + field + '/p' + str(asset['page']),
                            'image': asset['path'], 'crop_fraction': box,
                            'fields': {field: batch.DESCRIPTIONS[field]},
                            'output': str((directory / f"llm_p{asset['page']:03d}_target_{field}.json").relative_to(output)),
                            'localization_basis': 'UNIQUE_SOURCE_LABEL', 'needs_review': True})
        cases.setdefault(record['case_id'], []).append(final)
        for field in batch.ACCEPT.config['profiles'].get(final['effective_type'], {}).get('required_fields', []):
            review.append({'document_id': record['id'], 'sha256': record['sha256'], 'field': field,
                'accepted': final['decision']['extraction_stp_eligible'],
                'evidence_file': str(directory / 'final.json'), 'expected_value': '',
                'reviewed': False, 'reviewer': ''})
        if index % 25 == 0:
            print(f'Replayed {index}/{len(records)}', flush=True)
    batch.write(output / 'inventory.json', records)
    summary = batch.report(records, output, final=True)
    case_decisions = {case: decide_case(docs) for case, docs in cases.items()}
    batch.write(output / 'case_decisions.json', case_decisions)
    summary.update(fully_completed_cases=sum(d['case_complete'] for d in case_decisions.values()),
        case_stp_rate=sum(d['case_complete'] for d in case_decisions.values()) / len(cases),
        validation_status='DEVELOPMENT_REPLAY_INDEPENDENT_REVIEW_REQUIRED', new_cloud_calls=0)
    batch.write(output / 'summary.json', summary)
    priority = sorted([{'case_id': case, **decision} for case, decision in case_decisions.items()],
        key=lambda item: (len(item['unresolved_documents']), len(item['missing_roles'])))
    batch.write(output / 'case_priority.json', priority)
    recovery.sort(key=lambda job: next(i for i, case in enumerate(priority) if job['id'].startswith(case['case_id'] + '/')))
    batch.write(output / 'targeted_recovery_jobs.json', recovery)
    taxonomy = Counter(reason.split(':')[0] for docs in cases.values() for doc in docs
        for reason in doc['decision']['reason_codes'])
    batch.write(output / 'failure_taxonomy.json', dict(taxonomy))
    with (output / 'independent_review.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(review[0]))
        writer.writeheader()
        writer.writerows(review)
    paths = list((batch.ROOT / 'config').glob('uat_*.yaml')) + list(
        (batch.ROOT / 'workers/unstructured_extraction').glob('uat_*.py'))
    paths += [batch.ROOT / 'workers/unstructured_extraction' / name for name in
        ['extraction_acceptance.py', 'local_completion.py', 'observed_type.py']]
    paths += [Path(__file__).resolve(), batch.ROOT / 'scripts/run_uat_all.py']
    batch.write(output / 'replay_manifest.json', {'source': str(source), 'baseline_modified': False,
        'verified_page_assets': len(verified), 'documents': len(records),
        'configuration_hashes': {str(p.relative_to(batch.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    replay(args.source, args.output)
