"""Replay local UAT decisions from recorded layout evidence, without OCR calls."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from packages.layout_intelligence.engine import BundleDResult
from packages.runtime_profile.contracts import ROOT
from workers.unstructured_extraction.local_completion import LocalLayoutCompletion
from workers.unstructured_extraction.uat_inline import recover_inline
from workers.unstructured_extraction.uat_policy import content_matches, load_policy


def replay(source, output):
    source, output = Path(source), Path(output)
    rows = json.loads((source/'results.json').read_text(encoding='utf-8'))
    if len(rows) != 10 or not (source/'summary.json').exists():
        raise ValueError('Replay requires a completed ten-document run')
    output.mkdir(parents=True, exist_ok=False)
    service = LocalLayoutCompletion(profile_path=ROOT/'config/runtime_profiles/uat_evaluation_v1.yaml',
                                    labels_path=ROOT/'config/uat_layout_label_aliases.yaml')
    policy = load_policy()
    field_counts = Counter()
    for index, row in enumerate(rows, 1):
        directory = source/f'doc_{index:02d}'
        layouts = [BundleDResult.model_validate_json(path.read_text(encoding='utf-8'))
                   for path in sorted(directory.glob('layout_*.json'))]
        if len(layouts) != row['pages']:
            raise ValueError(f'Incomplete layout evidence: {directory}')
        for page in layouts:
            recover_inline(page, service.layout.labels.fields)
        text = ' '.join(line.text for page in layouts for line in page.lines)
        final = service.complete(row['sha256'], layouts, document_family='UAT_'+row['document_type'],
                                 type_verified=content_matches(row['document_type'], text, policy))
        target = output/f'doc_{index:02d}'
        target.mkdir()
        (target/'FinalClaim.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
        row['outcome'] = final['claim_decision']['disposition']
        row['reason'] = ';'.join(final['completion_reason_codes']+final['claim_decision']['reason_codes'])
        for field in final['field_decisions']:
            for reason in field['reason_codes']:
                field_counts[reason] += 1
    (output/'results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    with (output/'scorecard.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {'documents': len(rows), 'pages': sum(row['pages'] for row in rows),
        'outcomes': dict(Counter(row['outcome'] for row in rows)), 'source_run': str(source.resolve()),
        'reused_layout_and_ocr_evidence': True, 'new_ocr_calls': 0, 'route_mode': 'evaluation',
        'production_stp_rate': None, 'correct_stp_rate': None,
        'evaluation_stp_rate': sum(row['outcome'] in {'STP_SAFE', 'STP_STANDARD'} for row in rows)/len(rows),
        'field_reason_counts': dict(field_counts)}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    replay(args.input, args.output)
