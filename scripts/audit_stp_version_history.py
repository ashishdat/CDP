"""Offline historical STP audit: deduplicate and replay relevant function versions."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                          text=True, encoding='utf-8', check=True).stdout


def replay(source, symbol):
    from packages.evidence import builder
    from packages.evidence.models import FieldEvidenceBundle

    tree = ast.parse(source)
    node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == symbol), None)
    if node is None:
        return None
    function_text = ast.get_source_segment(source, node)
    namespace = dict(vars(builder))
    namespace['_CRITICAL'] = frozenset({'patient_name', 'patient_dob', 'insured_id_number', 'total_charge'})
    # Execute only this audited pure helper, never the historical module/main.
    exec(compile('from __future__ import annotations\n' + function_text, '<historical-function>', 'exec'), namespace)  # noqa: S102
    if symbol == '_append_unique_calendar_dob_e2':
        bundle = FieldEvidenceBundle(field_name='patient_dob')
        candidate = SimpleNamespace(value='01/02/2000', engine='rapidocr', provenance=None)
        namespace[symbol](bundle, 'patient_dob', [candidate])
        result = {'single_reader_mints_independent_E2': any(e.independent and e.evidence_class.value == 'E2' for e in bundle.items)}
    else:
        invalid = {'patient_name': 'PATIENT NAME', 'patient_dob': '02/30/2000',
                   'insured_id_number': 'X', 'total_charge': 'not an amount'}
        disposition, _ = namespace[symbol](invalid)
        result = {'invalid_present_fields_promoted_to_STP': disposition == 'TRUE_STP'}
    return {'function_sha256': hashlib.sha256(function_text.encode()).hexdigest(), **result}


def main():
    import yaml

    targets = [('packages/evidence/builder.py', '_append_unique_calendar_dob_e2'),
               ('packages/extraction_recovery/independent_case_router.py', 'promote_unstructured_fields')]
    audit = {'scope': 'All Git references for targeted acceptance helpers and DOB policies; isolated function replay, not full historical application execution',
             'cloud_calls': 0, 'function_versions': [], 'policy_versions': [], 'errors': []}
    for path, symbol in targets:
        commits = git('log', '--all', '--format=%H', '--', path).splitlines()
        versions = {}
        for commit in commits:
            try:
                result = replay(git('show', f'{commit}:{path}'), symbol)
                if result is None:
                    continue
                key = result['function_sha256']
                versions.setdefault(key, {'path': path, 'symbol': symbol, 'commits': [], **result})['commits'].append(commit)
            except (OSError, ValueError, TypeError, NameError, AttributeError, KeyError,
                    ImportError, subprocess.CalledProcessError) as exc:
                audit['errors'].append({'commit': commit, 'path': path, 'error': type(exc).__name__ + ': ' + str(exc)})
        current = replay((ROOT / path).read_text(encoding='utf-8'), symbol)
        audit['function_versions'].extend(versions.values())
        audit['function_versions'].append({'path': path, 'symbol': symbol, 'commits': ['WORKING_TREE'], **current})
    seen = {}
    for commit in git('log', '--all', '--format=%H', '--', 'config/evidence_policies.yaml').splitlines():
        source = git('show', f'{commit}:config/evidence_policies.yaml')
        policy = yaml.safe_load(source)
        dob = (policy.get('fields') or {}).get('patient_dob') or {}
        key = json.dumps(dob, sort_keys=True)
        seen.setdefault(key, {'dob_policy': dob, 'commits': []})['commits'].append(commit)
    audit['policy_versions'] = list(seen.values())
    output = ROOT / 'evaluation_results/version_accuracy_audit_20261005'
    output.mkdir(exist_ok=True)
    (output / 'history_replay.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'distinct_function_versions': len(audit['function_versions']),
                      'distinct_dob_policy_versions': len(audit['policy_versions']),
                      'replay_errors': len(audit['errors']),
                      'versions_minting_single_reader_E2': sum(v.get('single_reader_mints_independent_E2', False) for v in audit['function_versions']),
                      'versions_promoting_invalid_fields': sum(v.get('invalid_present_fields_promoted_to_STP', False) for v in audit['function_versions'])}))


if __name__ == '__main__':
    main()
