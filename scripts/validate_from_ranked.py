"""Resume saved ranked candidates through existing field validation only."""
import argparse
import hashlib
import json
from collections import Counter
from html import escape
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from packages.extraction_recovery import select_field_span, span_datatype_for_field
from packages.field_normalization import normalize
from packages.templates.registry import TemplateRegistry
from packages.validation_rules.engine import ValidationEngine
from packages.validation_rules.thresholds import ThresholdRegistry


def validate_candidate(row, field_type, engine, claim_id):
    candidate = row['ocr_candidate']
    raw = candidate.get('value') or candidate['raw_value']
    span = select_field_span(
        raw,
        span_datatype_for_field(row['field_id'], field_type),
        row['field_id'],
    )
    raw = span.selected_text
    normalized, ok = normalize(field_type, raw)
    field = SimpleNamespace(field_name=row['field_id'],
        field_id=uuid5(claim_id, row['candidate_id']), normalized_value=normalized,
        confidence=candidate['raw_confidence'])
    # Existing field dispatcher only: no claim-wide reconciliation or decision.
    checks = engine._validate_field(SimpleNamespace(claim_id=claim_id), field)
    reasons = [check.message or check.rule_name for check in checks]
    statuses = {check.status.value for check in checks}
    if not raw.strip():
        status = 'NO_VALUE'
        reasons.insert(0, 'NO_RAW_VALUE')
    elif not ok:
        status = 'INVALID'
        reasons.insert(0, 'NORMALIZATION_FAILED')
    elif 'INVALID' in statuses:
        status = 'INVALID'
    elif 'RANKING_MARGIN_LOW' in row.get('ranking_reason', []):
        status = 'AMBIGUOUS'
        reasons.insert(0, 'Existing ranking reported low margin; no reranking performed')
    elif 'NEEDS_REVIEW' in statuses:
        status = 'SUSPICIOUS'
    else:
        status = 'VALID'
        if not reasons:
            reasons.append('Normalization and configured confidence check passed; no content rule emitted')
    return {'field_id':row['field_id'], 'candidate_id':row['candidate_id'],
            'status':status, 'reason':reasons, 'normalized_value':normalized,
            'validator':['packages.field_normalization.normalize',
                         'packages.validation_rules.engine.ValidationEngine._validate_field']}, [c.model_dump(mode='json') for c in checks]


def run(source, output, template_id, template_version):
    source, output = Path(source), Path(output)
    payload = source.read_bytes()
    ranked = json.loads(payload)
    if ranked.get('status') != 'SUCCESS':
        raise ValueError('Successful RankedCandidates required')
    template = TemplateRegistry.load_from_directory().get(template_id, template_version)
    types = {field.field_name:field.field_type for field in template.field_regions}
    engine = ValidationEngine(ThresholdRegistry.load_from_directory())
    claim_id = uuid5(NAMESPACE_URL, ranked['document_id'])
    output.mkdir(parents=True, exist_ok=False)
    report = {'type':'ValidationResults','status':'RUNNING','document_id':ranked['document_id'],
              'source_sha256':hashlib.sha256(payload).hexdigest(),
              'template_id':template_id,'template_version':template_version,
              'results':[],'stop_after':'validators'}
    telemetry = {'events':[], 'status_mapping':{'NEEDS_REVIEW':'SUSPICIOUS'},
                 'scope':'Individual candidate normalization, configured field rules and confidence only; no claim reconciliation',
                 'upstream_rerun':False,'decision_called':False,'evidence_called':False}
    try:
        seen = set()
        for row in ranked['ranked_candidates']:
            if row['candidate_id'] in seen:
                raise ValueError('Duplicate candidate ID')
            seen.add(row['candidate_id'])
            started = perf_counter()
            result, checks = validate_candidate(row,types[row['field_id']],engine,claim_id)
            index = len(telemetry['events'])
            result['telemetry_reference'] = f'validator_telemetry.json#/events/{index}'
            report['results'].append(result)
            telemetry['events'].append({'field_id':row['field_id'],'candidate_id':row['candidate_id'],
                'status':result['status'],'latency_ms':(perf_counter()-started)*1000,
                'field_type':types[row['field_id']], 'raw_value':row['ocr_candidate']['raw_value'],
                'raw_confidence':row['ocr_candidate']['raw_confidence'],
                'normalized_value':result['normalized_value'],'checks':checks})
        report['status'] = 'COMPLETED'
    except Exception as exc:
        report['status'] = 'FAILED'
        telemetry['failure'] = {'type':type(exc).__name__,'reason':str(exc)}
        raise
    finally:
        report['counts'] = dict(Counter(r['status'] for r in report['results']))
        (output/'ValidationResults.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        (output/'validator_telemetry.json').write_text(json.dumps(telemetry,indent=2,allow_nan=False),encoding='utf-8')
        # No raw claim values in the shareable status summary.
        rows = ''.join('<tr><td>'+escape(r['field_id'])+'</td><td>'+escape(r['candidate_id'])+'</td><td>'+r['status']+'</td><td>'+escape(r['telemetry_reference'])+'</td></tr>' for r in report['results'])
        (output/'validation_summary.html').write_text('<!doctype html><meta charset="utf-8"><title>Validation summary</title><style>body{font:15px system-ui;margin:25px}td,th{border:1px solid #ccc;padding:8px}</style><h1>Field validation: '+report['status']+'</h1><p>'+escape(json.dumps(report['counts']))+'</p><p>Candidate-level checks only. VALID is not a claim decision. Original checks and reasons are in local telemetry. No upstream reruns, Decision, or Evidence.</p><table><tr><th>Field</th><th>Candidate</th><th>Status</th><th>Telemetry</th></tr>'+rows+'</table>',encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ranked_candidates')
    parser.add_argument('output_directory')
    parser.add_argument('--template-id', required=True)
    parser.add_argument('--template-version', required=True)
    args = parser.parse_args()
    result = run(args.ranked_candidates,args.output_directory,args.template_id,args.template_version)
    print(json.dumps({'status':result['status'],'results':len(result['results']),'counts':result['counts']}))
