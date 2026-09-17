"""Verify the selected Golden V3 reference; start evaluation only with --run."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly start the 100-document extraction benchmark.')
    args = parser.parse_args()
    config = json.loads((ROOT/'config/evaluation/golden_truth_v3.json').read_text())
    dataset = ROOT/config['dataset_path']
    for name, expected in config['files_sha256'].items():
        actual = hashlib.sha256((dataset/name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f'Golden dataset changed: {name}')
    worktree = ROOT/config['evaluator_worktree']
    commit = subprocess.check_output(['git', '-C', str(worktree), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != config['evaluator_commit']:
        raise ValueError('Evaluator commit differs from configured baseline')
    print(f"Verified {config['dataset_id']}: {config['documents']} documents, {config['field_labels']} field labels, {config['ub_service_rows']} UB service rows.", flush=True)
    if not args.run:
        print('No OCR or testing started. Use --run to start the configured benchmark.')
        return 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = ROOT/'evaluation_results'/('golden_v3_feb4f96_'+stamp)
    return subprocess.call([str(ROOT/config['python']), '-u', '-m', config['evaluator_module'],
                            '--dataset', str(dataset), '--cms', '50', '--ub', '50',
                            '--output', str(output)], cwd=worktree)


if __name__ == '__main__':
    raise SystemExit(main())
