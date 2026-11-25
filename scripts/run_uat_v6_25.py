"""Bounded page recovery and final audit for the frozen 25-case cohort."""
import argparse
import csv
import shutil
from collections import Counter
from pathlib import Path

from scripts import run_uat_all as batch

SOURCE = Path('runs/uat_25_cases_v5_run_20261125')
OUT = Path('runs/uat_25_cases_v6_20261125')
# Pages with a missing field or a contradictory source reading, not whole files.
AFFECTED = {
    '3DYK964154/doc_003': {1: ['report_date', 'tmt_interpretation']},
    '3DYK977417/doc_001': {1: ['patient_name', 'report_date']},
    '3DYL039921/doc_001': {1: ['patient_name', 'report_date', 'ecg_interpretation']},
    '3DYL061159/doc_007': {1: ['report_date', 'ecg_interpretation']},
    '3GYL039874/doc_004': {1: ['patient_name']},
    '3GYL049205/doc_003': {1: ['tmt_interpretation'], 9: ['report_date'], 10: ['report_date']},
    '3NNK387629/doc_004': {1: ['report_date', 'tmt_interpretation'], 6: ['report_date']},
    '3QNK343534/doc_002': {3: ['patient_name']},
    '3QNK343534/doc_006': {1: ['patient_name', 'report_date', 'ecg_interpretation']},
    '3WYK999875/doc_002': {3: ['patient_name', 'patient_dob'], 6: ['examination_date']},
}


def csv_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def queue():
    records = batch.read(OUT / 'inventory.json')
    rows = csv_rows(SOURCE / 'review/category_b_root_causes_left.csv')
    assert set(AFFECTED) == {r['document_id'] for r in rows if r['primary_root_cause'] == 'OCR miss'}
    jobs = []
    for record in records:
        record['apply_recovery_v6'] = True
        directory = Path(record['directory'])
        local = batch.read(directory / 'local.json')
        for asset in local['assets']:
            page = asset['page']
            if page not in AFFECTED.get(record['id'], {}):
                continue
            target = directory / f'di_page_{page:03d}.json'
            backup = directory / f'baseline_di_page_{page:03d}.json'
            if target.exists() and not backup.exists():
                shutil.copyfile(target, backup)
            jobs.append({'id': record['id'] + f'/v6_affected/p{page}', 'image': asset['path'],
                         'output': str((directory / f'fresh_di_page_{page:03d}.json').relative_to(OUT.resolve())),
                         'document_type': record['declared_type'], 'affected_fields': AFFECTED[record['id']][page]})
    batch.write(OUT / 'inventory.json', records)
    batch.write(OUT / 'affected_di_jobs.json', jobs)
    schema = [r for r in rows if r['primary_root_cause'] == 'Schema mapping']
    counts = Counter((r['type'], reason.split(':')[-1]) for r in schema for reason in r['remaining_reasons'].split(';'))
    batch.write(OUT / 'schema_mapping_breakdown.json', [{'type': k[0], 'field': k[1], 'documents': v}
                for k, v in counts.most_common()])
    print('Affected DI pages:', len(jobs), 'documents:', len(AFFECTED), flush=True)


def install_di():
    for job in batch.read(OUT / 'affected_di_jobs.json'):
        path = OUT / job['output']
        result = batch.read(path)
        if result['status'] == 'SUCCESS':
            page = int(job['id'].rsplit('/p', 1)[1])
            result['recovery_scope'] = 'V6_AFFECTED_OCR_PAGE'
            batch.write(path.parent / f'di_page_{page:03d}.json', result)


def crop_queue():
    # Source-inspected regions; exclude the rest of each page from Claude.
    regions = {
        ('3DYK964154/doc_003', 1): [(.0, .24, .65, .36, ['report_date']), (.0, .47, .75, .61, ['tmt_interpretation'])],
        ('3DYK977417/doc_001', 1): [(.0, .38, .67, .59, ['patient_name', 'report_date'])],
        ('3DYL039921/doc_001', 1): [(.08, .66, .86, .74, ['patient_name', 'report_date']), (.34, .39, .76, .56, ['ecg_interpretation'])],
        ('3DYL061159/doc_007', 1): [(.0, .36, 1., .57, ['report_date', 'ecg_interpretation'])],
        ('3GYL039874/doc_004', 1): [(.04, .12, .9, .29, ['patient_name'])],
        ('3GYL049205/doc_003', 1): [(.03, .60, .93, .73, ['tmt_interpretation'])],
        ('3NNK387629/doc_004', 1): [(.02, .55, .85, .67, ['tmt_interpretation'])],
        ('3QNK343534/doc_002', 3): [(.05, .13, .97, .30, ['patient_name'])],
        ('3QNK343534/doc_006', 1): [(.01, .17, .99, .43, ['patient_name', 'ecg_interpretation']), (.25, .52, .86, .64, ['report_date'])],
        ('3WYK999875/doc_002', 3): [(.05, .10, .96, .28, ['patient_name', 'patient_dob'])],
        ('3WYK999875/doc_002', 6): [(.02, .55, .75, .85, ['examination_date'])],
    }
    jobs = []
    for record in batch.read(OUT / 'inventory.json'):
        if record['id'] not in AFFECTED:
            continue
        doc = batch.evaluate(record, final=True)
        blocked = {r.split(':')[-1] for r in doc['decision']['reason_codes']}
        for asset in doc['assets']:
            for x0, y0, x1, y1, fields in regions.get((record['id'], asset['page']), []):
                fields = [field for field in fields if field in blocked]
                if not fields:
                    continue
                number = len(jobs) + 1
                jobs.append({'id': record['id'] + f'/v6_missing_crop/{number}', 'image': asset['path'],
                             'crop_fraction': [x0, y0, x1, y1],
                             'fields': {f: batch.DESCRIPTIONS[f] + ' Transcribe only what is visible. Preserve short years, spelling and initials. Do not infer from another document.' for f in fields},
                             'output': str((Path(record['directory']) / f'llm_v6_missing_p{asset["page"]:03d}_{number}.json').relative_to(OUT.resolve())),
                             'purpose': 'AFFECTED_FIELD_UNRESOLVED_AFTER_DI'})
    batch.write(OUT / 'affected_field_crop_jobs.json', jobs)
    print('Unresolved field crop calls:', len(jobs), flush=True)


def local_crops():
    from PIL import Image

    from packages.ocr.tesseract_adapter import TesseractTextExtractor
    from packages.ocr.text_extraction import TextLine
    from workers.unstructured_extraction.uat_evidence import locate_value
    for job in batch.read(OUT / 'affected_field_crop_jobs.json'):
        path = OUT / job['output']
        result = batch.read(path)
        if result['status'] != 'SUCCESS':
            continue
        record = next(r for r in batch.read(OUT / 'inventory.json') if r['id'] == job['id'].split('/v6_')[0])
        directory = Path(record['directory'])
        assets = batch.read(directory / 'local.json')['assets']
        page = next(a['page'] for a in assets if a['path'] == job['image'])
        with Image.open(job['image']) as im:
            frac = job['crop_fraction']
            box = tuple(round(v * (im.width if i % 2 == 0 else im.height)) for i, v in enumerate(frac))
            crop = im.crop(box)
            crop = crop.resize((crop.width * 2, crop.height * 2))
            raw = TesseractTextExtractor(psm=6).extract(crop)
        lines = [TextLine(l.text, l.x0 / 2 + box[0], l.y0 / 2 + box[1],
                          l.x1 / 2 + box[0], l.y1 / 2 + box[1], l.confidence) for l in raw]
        target = directory / 'local_field_recovery_v6.json'
        recovered = batch.read(target) if target.exists() else {'candidates': {}, 'cloud_calls': 0}
        for field in result['fields']:
            if not field.get('value') or field.get('insufficient_evidence'):
                continue
            item = locate_value(field['value'], [(page, lines)], page_number=page,
                                mapping_provider='claude_crop_local_tesseract', field_name=field['field_name'])
            if item:
                item.update(mapping_record=str(path.resolve()), source_image=job['image'],
                            local_ocr_crop=job['crop_fraction'], engine='local_tesseract_crop+claude_mapping')
                recovered['candidates'].setdefault(field['field_name'], []).append(item)
        batch.write(directory / ('ocr_' + path.stem + '_local.json'), {'source_image': job['image'], 'crop_box': box,
                    'scale': 2, 'ocr_lines': [vars(l) for l in lines]})
        batch.write(target, recovered)
        print('Local crop OCR:', job['id'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['queue', 'install-di', 'crop-queue', 'local-crops'], required=True)
    args = parser.parse_args()
    {'queue': queue, 'install-di': install_di, 'crop-queue': crop_queue, 'local-crops': local_crops}[args.stage]()
