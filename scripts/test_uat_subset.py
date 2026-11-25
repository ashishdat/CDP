"""Isolate a deterministic case subset and reconcile targeted provider recovery."""
import argparse
import shutil
from collections import Counter
from pathlib import Path

from scripts import run_uat_all as batch


def prepare(source, output, count):
    source, output = Path(source).resolve(), Path(output).resolve()
    records = batch.read(source / 'inventory.json')
    cases = list(dict.fromkeys(row['case_id'] for row in records))[:count]
    if len(cases) != count:
        raise ValueError('Insufficient cases')
    output.mkdir(parents=True, exist_ok=False)
    records = [row for row in records if row['case_id'] in cases]
    for record in records:
        old = Path(record['directory'])
        directory = output / 'cases' / record['id']
        directory.mkdir(parents=True)
        for path in old.glob('*.json'):
            shutil.copyfile(path, directory / path.name)
        record['directory'] = str(directory)
        for name in ['local.json', 'final.json']:
            doc = batch.read(directory / name)
            doc['directory'] = str(directory)
            batch.write(directory / name, doc)
    batch.write(output / 'inventory.json', records)
    jobs = [job for job in batch.read(source / 'targeted_recovery_jobs.json')
            if job['id'].split('/')[0] in cases]
    batch.write(output / 'targeted_recovery_jobs.json', jobs)
    baseline = batch.report(records, output, final=True)
    batch.write(output / 'baseline_summary.json', baseline)
    batch.write(output / 'test_manifest.json', {'source': str(source), 'selected_cases': cases,
        'selection': 'First cases in recorded archive inventory order; no outcome filtering',
        'development_cases': True, 'independent_accuracy_validation': False,
        'reused_local_ocr_and_di': True, 'new_claude_jobs': len(jobs)})
    print(f'{len(cases)} cases, {len(records)} documents, {len(jobs)} targeted Claude jobs')


def finish(output):
    output = Path(output).resolve()
    jobs = batch.read(output / 'targeted_recovery_jobs.json')
    results = [batch.read(output / job['output']) for job in jobs]
    if any(result['status'] not in {'SUCCESS', 'FAILED'} for result in results):
        raise ValueError('Provider jobs still pending')
    records = batch.read(output / 'inventory.json')
    for record in records:
        batch.evaluate(record, final=True)
    summary = batch.report(records, output, final=True)
    baseline = batch.read(output / 'baseline_summary.json')
    source = Path(batch.read(output / 'test_manifest.json')['source'])
    changes = []
    for record in records:
        before = batch.read(source / 'cases' / record['id'] / 'final.json')['decision']
        after = batch.read(Path(record['directory']) / 'final.json')['decision']
        if before['extraction_stp_eligible'] != after['extraction_stp_eligible']:
            changes.append({'document_id': record['id'], 'before': before['disposition'],
                            'after': after['disposition'], 'remaining_reasons': after['reason_codes']})
    batch.write(output / 'decision_changes.json', changes)
    batch.write(output / 'targeted_provider_summary.json', {
        'statuses': dict(Counter(result['status'] for result in results)),
        'reported_tokens': {key: sum(result.get('usage', {}).get(key, 0) for result in results)
                            for key in ['input_tokens', 'output_tokens', 'total_tokens']},
        'returned_fields': sum(len(result.get('fields', [])) for result in results),
        'abstained_fields': sum(field.get('insufficient_evidence', False) or not field.get('value')
            for result in results for field in result.get('fields', []))})
    summary.update(new_claude_jobs=len(jobs), successful_claude_jobs=sum(
        result['status'] == 'SUCCESS' for result in results), new_di_calls=0,
        baseline_completed_documents=baseline['completed_documents'],
        document_completion_gain=summary['completed_documents'] - baseline['completed_documents'],
        validation_status='DEVELOPMENT_CASE_TEST_ACCURACY_UNMEASURED')
    batch.write(output / 'summary.json', summary)
    print(summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runs/uat_plan_v3b_20261124'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', type=int, default=25)
    parser.add_argument('--finish', action='store_true')
    args = parser.parse_args()
    if args.finish:
        finish(args.output)
    else:
        prepare(args.source, args.output, args.cases)
