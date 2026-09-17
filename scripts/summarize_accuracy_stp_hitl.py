"""Report live operational rates and accuracy against independently reviewed CSV labels.

Labels: document,field_name,expected_value,reviewed,reviewer.
Blank expected_value is a verified empty value only when reviewed=true.
Run from the workspace: python -m scripts.summarize_accuracy_stp_hitl RUN_DIR
"""
from __future__ import annotations

import argparse
import csv
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CRITICAL = ('patient_dob', 'total_charge', 'patient_name', 'insured_id_number', 'insured_name')
AUTO = {'AUTO_ACCEPTED', 'REFERENCE_CONFIRMED'}


def normalized(value):
    return ' '.join(str(value if value is not None else '').split())


def build_report(root, labels=None):
    root = Path(root)
    by_document = {}
    ledger = root / 'results.jsonl'
    if ledger.exists():
        for line in ledger.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # A live writer can have an unfinished trailing record.
            if row.get('finished'):
                by_document[row['document']] = row
    rows = list(by_document.values())
    n = len(rows)
    counts = Counter(r.get('disposition', 'UNKNOWN') for r in rows)
    stp = sum(bool(r.get('completed') and r.get('true_stp')) for r in rows)
    field_hitl = sum(bool(r.get('completed') and not r.get('true_stp')) for r in rows)
    registration_hitl = counts['REGISTRATION_FAILED']
    failures = n - stp - field_hitl - registration_hitl
    requested = json.loads((root / 'launch.json').read_text(encoding='utf-8-sig'))['documents']
    def rate(count, denominator=n):
        return count / denominator if denominator else None
    predictions = {}
    for row in rows:
        final = root / 'claims' / row['claim_id'] / 'final' / 'FinalClaim.json'
        if final.exists():
            payload = json.loads(final.read_text(encoding='utf-8'))
            for field in (payload.get('decision') or payload).get('field_decisions', []):
                predictions[row['document'], field['field_name']] = field
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'requested': requested, 'processed': n, 'pending': requested - n,
        'status': 'complete' if n == requested else 'partial',
        'dispositions': dict(counts),
        'stp': {'count': stp, 'rate_of_processed': rate(stp),
                'rate_of_completed': rate(stp, stp + field_hitl)},
        'hitl': {'completed_field_review': field_hitl, 'registration_review': registration_hitl,
                 'total': field_hitl + registration_hitl,
                 'rate_of_processed': rate(field_hitl + registration_hitl)},
        'technical_failures': {'count': failures, 'rate_of_processed': rate(failures)},
        'accuracy': {'status': 'unavailable', 'reason': 'No reviewed labels for processed documents'},
        'definitions': {
            'stp': 'Pipeline completed and requires no review; correctness is not implied.',
            'hitl': 'Completed requiring review plus registration rejections needing intervention.',
            'technical_failures': 'Separate from STP and HITL; all counts partition processed documents.',
            'accuracy': 'Exact match after whitespace normalization; case and punctuation retained.',
            'scope': 'Per-document outcomes emitted by the existing CMS1500 runner; not all-page accuracy.',
        },
    }
    if labels:
        scored = []
        seen = set()
        pending_labels = 0
        with Path(labels).open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            required = {'document', 'field_name', 'expected_value', 'reviewed', 'reviewer'}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError('Label CSV must contain: ' + ', '.join(sorted(required)))
            for label in reader:
                if label['reviewed'].strip().lower() != 'true':
                    continue
                if not label['reviewer'].strip():
                    raise ValueError('Reviewed label is missing reviewer')
                key = label['document'], label['field_name']
                if key in seen:
                    raise ValueError(f'Duplicate reviewed label: {key}')
                seen.add(key)
                if key[0] not in by_document:
                    pending_labels += 1
                    continue
                prediction = predictions.get(key)
                correct = prediction is not None and normalized(prediction.get('selected_value')) == normalized(label['expected_value'])
                scored.append({'document': key[0], 'field_name': key[1], 'correct': correct,
                               'auto_accepted': prediction is not None and prediction.get('disposition') in AUTO})
        if scored:
            critical = [s for s in scored if s['field_name'] in CRITICAL]
            accepted = [s for s in scored if s['auto_accepted']]
            report['accuracy'] = {
                'status': 'measured_on_reviewed_subset', 'labels': str(Path(labels).resolve()),
                'reviewed_fields': len(scored), 'correct_fields': sum(s['correct'] for s in scored),
                'field_accuracy': sum(s['correct'] for s in scored) / len(scored),
                'critical_fields_reviewed': len(critical),
                'critical_field_accuracy': rate(sum(s['correct'] for s in critical), len(critical)),
                'auto_accepted_fields_reviewed': len(accepted),
                'auto_accepted_field_accuracy': rate(sum(s['correct'] for s in accepted), len(accepted)),
                'false_auto_accepts': sum(not s['correct'] for s in accepted),
                'reviewed_labels_awaiting_processing': pending_labels,
                'coverage_note': 'Applies only to reviewed fields; not an estimate for all 1000 documents.',
            }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--labels', type=Path)
    parser.add_argument('--prepare-labels-from-zip', type=Path)
    args = parser.parse_args()
    if args.prepare_labels_from_zip:
        sheet = args.run_dir / 'critical_field_labels.csv'
        with zipfile.ZipFile(args.prepare_labels_from_zip) as archive:
            documents = sorted(n for n in archive.namelist() if not n.endswith('/'))
        # Exclusive creation protects any manual labels already entered.
        with sheet.open('x', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['document', 'field_name', 'expected_value', 'reviewed', 'reviewer'])
            for document in documents:
                for field in CRITICAL:
                    writer.writerow([document, field, '', 'false', ''])
    report = build_report(args.run_dir, args.labels)
    target = args.run_dir / 'accuracy_stp_hitl.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
