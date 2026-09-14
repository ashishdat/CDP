"""Assemble saved stage artifacts into an extraction result; execute no stage."""
import argparse
import hashlib
import json
from collections import Counter
from html import escape
from pathlib import Path


def load(path):
    path = Path(path)
    data = path.read_bytes()
    return json.loads(data), {'path':str(path), 'sha256':hashlib.sha256(data).hexdigest()}


def unique(items, key):
    indexed = {}
    for item in items:
        if item[key] in indexed:
            raise ValueError(f'Duplicate {key}: {item[key]}')
        indexed[item[key]] = item
    return indexed


def assemble(ocr_path, ranking_path, validation_path, output):
    ocr, op = load(ocr_path)
    ranking, rp = load(ranking_path)
    validation, vp = load(validation_path)
    geometry, gp = load(ocr['geometry_reference'])
    if (ocr['status'], ranking['status'], validation['status'], geometry['status']) != (
            'COMPLETED', 'SUCCESS', 'COMPLETED', 'SUCCESS'):
        raise ValueError('All source stages must be completed successfully')
    if ranking['source_sha256'] != op['sha256'] or validation['source_sha256'] != rp['sha256'] or ocr['geometry_sha256'] != gp['sha256']:
        raise ValueError('Stage artifact hash chain mismatch')
    if len({ocr['document_id'], ranking['document_id'], validation['document_id']}) != 1:
        raise ValueError('Document identity mismatch')
    if len({ocr['page_number'], ranking['page_number'], geometry['page_number']}) != 1:
        raise ValueError('Page identity mismatch')
    fields = unique(ocr['fields'], 'field')
    regions = unique(geometry['fields'], 'field')
    ranked = unique(ranking['ranked_candidates'], 'candidate_id')
    validated = unique(validation['results'], 'candidate_id')
    if set(ranked) != set(validated) or set(fields) != set(regions):
        raise ValueError('Missing or unexpected fields/candidate validation')
    telemetry = {}
    for name, parent, filename in [('ocr', Path(ocr_path).parent, 'ocr_telemetry.json'),
                                   ('ranking', Path(ranking_path).parent, 'ranking_telemetry.json'),
                                   ('validators', Path(validation_path).parent, 'validator_telemetry.json')]:
        content, provenance = load(parent / filename)
        telemetry[name] = {**provenance, 'recorded':content}
    def check_reference(row, stage):
        ref = row['telemetry_reference']
        path, fragment = ref.split('#/events/')
        if path != Path(telemetry[stage]['path']).name:
            raise ValueError('Telemetry file mismatch')
        event = telemetry[stage]['recorded']['events'][int(fragment)]
        if event['field_id'] != row['field_id']:
            raise ValueError('Telemetry field mismatch')
        if stage == 'validators' and event['candidate_id'] != row['candidate_id']:
            raise ValueError('Telemetry candidate mismatch')
    result_fields = []
    consumed = set()
    for name, field in fields.items():
        region = regions[name]['result']['aligned_roi']
        if field['canonical_region'] != [region[k] for k in ('x0','y0','x1','y1')]:
            raise ValueError('Canonical region mismatch')
        candidates = []
        for index, original in enumerate(field['candidates']):
            cid = f'{name}:{index}'
            candidate, check = ranked[cid], validated[cid]
            if candidate['field_id'] != name or check['field_id'] != name or candidate['ocr_candidate'] != original:
                raise ValueError('Candidate lineage mismatch')
            check_reference(candidate, 'ranking')
            check_reference(check, 'validators')
            consumed.add(cid)
            candidates.append(candidate)
        winners = [c for c in candidates if c['is_winner']]
        if candidates and len(winners) != 1:
            raise ValueError('Expected exactly one recorded winner')
        winner = winners[0] if winners else None
        if winner and any(c['winner'] != winner['candidate_id'] for c in candidates):
            raise ValueError('Inconsistent saved winner')
        check = validated[winner['candidate_id']] if winner else None
        result_fields.append({'field_name':name,'ocr':field,'ranked_candidate':winner,
            'alternatives':[c for c in candidates if not c['is_winner']],
            'candidate_validations':[validated[c['candidate_id']] for c in candidates],
            'validation':check, 'normalized_value':check['normalized_value'] if check else None,
            'confidence':winner['confidence'] if winner else None,
            'status':check['status'] if check else 'NO_VALUE'})
    if consumed != set(ranked):
        raise ValueError('Orphan ranked candidates')
    counts = dict(Counter(f['status'] for f in result_fields))
    warnings = [{'field_name':f['field_name'], 'status':f['status'],
                 'reason':f['validation']['reason'] if f['validation'] else ['No OCR candidate; validation not executed']}
                for f in result_fields if f['status'] != 'VALID']
    result = {'type':'ExtractionResult','status':'ASSEMBLED','document':{'document_id':ocr['document_id']},
        'page':{'page_number':ocr['page_number'],'coordinate_frame':ocr['coordinate_frame']},
        'field_results':result_fields,'statistics':{'fields':len(result_fields),'ocr_candidates':len(ranked),
            'validated_candidates':len(validated),'field_status_counts':counts},
        'warnings':warnings,'errors':[], 'telemetry':telemetry,
        'source_artifacts':{'geometry':gp,'ocr':op,'ranking':rp,'validation':vp},
        'confidence_basis':'Saved winning candidate raw OCR confidence; not document confidence',
        'stop_after':'extraction_result','decision_called':False,'evidence_called':False,
        'note':'ASSEMBLED means artifact assembly completed; it does not mean fields or claim accepted.'}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'ExtractionResult.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    rows = ''.join('<tr><td>'+escape(f['field_name'])+'</td><td>'+escape(f['status'])+'</td><td>'+escape(str(f['confidence']))+'</td></tr>' for f in result_fields)
    (output/'ExtractionSummary.html').write_text('<!doctype html><meta charset="utf-8"><title>Extraction summary</title><style>body{font:15px system-ui;margin:25px}td,th{padding:8px;border:1px solid #ccc}</style><h1>Extraction result assembled</h1><p>'+escape(json.dumps(result['statistics']))+'</p><p>Raw and normalized values remain in the local JSON. Missing candidates are NO_VALUE, not validator results. No upstream stages, Decision, or Evidence executed.</p><table><tr><th>Field</th><th>Status</th><th>Raw OCR confidence</th></tr>'+rows+'</table>',encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['ocr_candidates','ranked_candidates','validation_results','output_directory']:
        parser.add_argument(name)
    args = parser.parse_args()
    result = assemble(args.ocr_candidates,args.ranked_candidates,args.validation_results,args.output_directory)
    print(json.dumps(result['statistics']))
