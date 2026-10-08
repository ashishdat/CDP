"""Offline evaluation-only import of operator-verified case labels and source identities."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ALIASES = {'member_id': 'insured_id_number', 'total_charges': 'total_charge'}


def import_labels(labels_path: Path, manifest_path: Path) -> dict:
    labels = json.loads(labels_path.read_text(encoding='utf-8-sig'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    identities = {case['id']: case for case in manifest['cases']}
    if len(identities) != len(manifest['cases']):
        raise ValueError('Duplicate case identity')
    claims, unresolved, seen = {}, [], set()
    for case in labels['cases']:
        cid = case['case_id']
        if cid in seen or cid not in identities:
            raise ValueError('Duplicate or unmapped label case')
        seen.add(cid)
        identity = identities[cid]
        source = (manifest_path.parent / identity['original']).resolve()
        if not source.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError('Source identity escapes the supplied manifest')
        if hashlib.sha256(source.read_bytes()).hexdigest() != identity['source_sha256']:
            raise ValueError('Source image hash does not match the verified case')
        fields = {}
        for name, field in case['labels'].items():
            canonical = ALIASES.get(name, name)
            value = field.get('value')
            if (case.get('verified') is True and field.get('status') == 'verified'
                    and value is not None and str(value).strip()):
                fields[canonical] = {'value': str(value), 'confidence': 'GOLD',
                    'verification_status': 'OPERATOR_SUPPLIED_VERIFIED',
                    'source': str(labels_path.resolve()), 'case_id': cid}
            else:
                unresolved.append({'case_id': cid, 'field': canonical,
                                   'status': field.get('status', 'unverified')})
        key = identity['document'].replace('/', '__')
        if key in claims:
            raise ValueError('Multiple label cases map to one document')
        claims[key] = {'document': identity['document'],
                       'source_sha256': identity['source_sha256'], 'fields': fields}
    return {'schema_version': 'source-bound-verified-labels-v1',
            'created_by': 'operator_supplied_verified_case_import',
            'labels_sha256': hashlib.sha256(labels_path.read_bytes()).hexdigest(),
            'identity_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'qualification': 'Operator-marked verified labels; source identity hashes checked; development set',
            'runtime_use_allowed': False, 'claims': claims,
            'unresolved_fields': unresolved}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a fresh output file; never overwrite provided labels')
    report = import_labels(args.labels, args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'claims': len(report['claims']),
                      'verified_fields': sum(len(c['fields']) for c in report['claims'].values()),
                      'unresolved_fields': len(report['unresolved_fields'])}))


if __name__ == '__main__':
    main()
