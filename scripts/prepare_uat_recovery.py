"""Prepare case-prioritized, source-localized recovery jobs without cloud calls."""
import argparse
from pathlib import Path

from packages.layout_intelligence.engine import BundleDResult
from scripts import run_uat_all as batch
from workers.unstructured_extraction.uat_cases import decide_case
from workers.unstructured_extraction.uat_localization import field_region


def prepare(output):
    output = Path(output).resolve()
    records = batch.read(output / 'inventory.json')
    cases = {}
    jobs = []
    for record in records:
        directory = Path(record['directory'])
        doc = batch.read(directory / 'final.json')
        cases.setdefault(record['case_id'], []).append(doc)
        if doc['decision']['extraction_stp_eligible']:
            continue
        gaps = {reason.split(':', 1)[1] for reason in doc['decision']['reason_codes'] if ':' in reason}
        for field in sorted(gaps):
            if field not in batch.DESCRIPTIONS:
                continue
            aliases = batch.SERVICE.layout.labels.fields.get(field, {}).get('aliases', [])
            for asset, path in zip(doc['assets'], doc['layouts'], strict=True):
                layout = BundleDResult.model_validate_json(Path(path).read_text(encoding='utf-8'))
                box = field_region(layout, aliases, asset['width'], asset['height'])
                if box:
                    jobs.append({'id': record['id'] + '/' + field + '/p' + str(asset['page']),
                        'image': asset['path'], 'crop_fraction': box,
                        'fields': {field: batch.DESCRIPTIONS[field]},
                        'output': str((directory / f"llm_p{asset['page']:03d}_target_{field}.json").relative_to(output)),
                        'localization_basis': 'UNIQUE_SOURCE_LABEL'})
    decisions = {case: decide_case(docs) for case, docs in cases.items()}
    priority = sorted([{'case_id': case, **decision} for case, decision in decisions.items()],
        key=lambda item: (len(item['unresolved_documents']), len(item['missing_roles'])))
    ranks = {case['case_id']: index for index, case in enumerate(priority)}
    jobs.sort(key=lambda job: ranks[job['id'].split('/')[0]])
    batch.write(output / 'case_decisions.json', decisions)
    batch.write(output / 'case_priority.json', priority)
    batch.write(output / 'targeted_recovery_jobs.json', jobs)
    previous = batch.read(output / 'summary.json')
    summary = batch.report(records, output, final=True)
    for key in ['validation_status', 'new_cloud_calls']:
        if key in previous:
            summary[key] = previous[key]
    batch.write(output / 'summary.json', summary)
    print(f'Prepared {len(jobs)} field crops; no cloud calls made')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    prepare(parser.parse_args().output)
