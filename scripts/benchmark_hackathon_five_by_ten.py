"""Fixed-seed configurable local benchmark draws from five hackathon pools."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import benchmark_hackathon_four_corpora as benchmark

SEED = 20261005


def draw(pool, excluded, seed, sample_size=10):
    groups = defaultdict(list)
    for document in sorted(set(pool) - excluded):
        groups[document.split('/')[0]].append(document)
    total = sum(map(len, groups.values()))
    if sample_size < 1 or total < sample_size:
        raise ValueError(f'Requested {sample_size} documents but only {total} are available')
    ideal = {group: sample_size * len(docs) / total for group, docs in groups.items()}
    allocation = {group: int(value) for group, value in ideal.items()}
    for group in sorted(groups, key=lambda g: (-(ideal[g] - allocation[g]), g))[:sample_size - sum(allocation.values())]:
        allocation[group] += 1
    rng = random.Random(seed)
    selected = sorted(doc for group in sorted(groups) for doc in rng.sample(groups[group], allocation[group]))
    assert len(selected) == len(set(selected)) == sample_size
    return selected, allocation


def prepare(output, *, seed=SEED, exclude_manifests=(), ground_truth=None, sample_size=10):
    if (output / 'benchmark_manifest.json').exists():
        raise ValueError('Use a fresh output directory for selection')
    output.mkdir(parents=True, exist_ok=True)
    previous = json.loads((benchmark.OUT / 'benchmark_manifest.json').read_text(encoding='utf-8'))
    sources = {entry['pool_size']: Path(entry['archive']) for entry in previous['corpora']}
    sources[100] = sources[300]
    pool300 = (ROOT / 'docs/metrics/similar_sample_300_v1/selected_documents.txt').read_text().splitlines()
    pool1000 = (ROOT / 'docs/metrics/similar_sample_1000_v1/selected_documents.txt').read_text().splitlines()
    pools = {100: pool300[:100], 300: pool300, 1000: pool1000}
    # Avoid the earlier 200-document benchmark as well as duplicates in this run.
    excluded = {doc for entry in previous['corpora'] for doc in entry['documents']}
    for path in exclude_manifests:
        excluded_manifest = json.loads(path.read_text(encoding='utf-8'))
        excluded.update(doc for entry in excluded_manifest['corpora'] for doc in entry['documents'])
    corpora, registrations = [], []
    for size in (100, 300, 1000, 5000, 10000):
        run = output / f'corpus_{size}'
        run.mkdir()
        with ZipFile(sources[size]) as source:
            names = sorted(n for n in source.namelist() if not n.endswith('/') and n.split('/')[0] in {'Group A', 'Group B', 'Group C', 'Group D'})
            pool = pools.get(size, names)
            if len(pool) != size or len(set(pool)) != size or not set(pool) <= set(names):
                raise ValueError(f'Invalid {size} pool membership')
            selected, allocation = draw(pool, excluded, seed + size, sample_size)
            archive = run / f'sample_{sample_size}.zip'
            pages, hashes = 0, {}
            with ZipFile(archive, 'w', compression=ZIP_STORED) as packed:
                for doc in selected:
                    payload = source.read(doc)
                    hashes[doc] = hashlib.sha256(payload).hexdigest()
                    with Image.open(BytesIO(payload)) as image:
                        pages += image.n_frames
                    packed.writestr(ZipInfo(doc, date_time=(2026, 10, 5, 0, 0, 0)), payload)
        excluded.update(selected)
        dataset_id = f'HACKATHON_REVIEW_{size}_{sample_size}_{seed}'
        description = f'{sample_size}-document development draw from hackathon {size} pool; seed {seed + size}; not an independent holdout.'
        dataset = run / 'dataset.yaml'
        dataset.write_text(yaml.safe_dump({'dataset_id': dataset_id, 'root': str(archive.resolve()),
                           'pages': pages, 'documents': sample_size, 'description': description}), encoding='utf-8')
        (run / 'selected_documents.txt').write_text('\n'.join(selected) + '\n', encoding='utf-8')
        digest = benchmark.sha(archive)
        entry = {'pool_size': size, 'sample_size': sample_size, 'seed': seed + size, 'allocation': allocation,
                 'archive': str(sources[size]), 'dataset': str(dataset.resolve()), 'dataset_id': dataset_id,
                 'sample_archive': str(archive.resolve()), 'sample_archive_sha256': digest,
                 'documents': selected, 'source_sha256': hashes, 'sample_pages': pages}
        if size == 100:
            entry['pool_definition'] = 'Historical first 100 entries of similar_sample_300_v1/selected_documents.txt'
        benchmark.write_json(run / 'selection_manifest.json', entry)
        corpora.append(entry)
        registrations.append(f'    {dataset_id!r}: DatasetMetadata(dataset_id={dataset_id!r}, version=1, type=DatasetType.VALIDATION, pages={pages}, documents={sample_size}, hash={digest!r}, description={description!r}, source={str(archive.relative_to(ROOT))!r}),')
        print(f'Prepared pool={size} documents={sample_size} pages={pages} groups={allocation}', flush=True)
    registry = ROOT / 'datasets/registry.py'
    text = registry.read_text(encoding='utf-8')
    if any(entry['dataset_id'] in text for entry in corpora):
        raise ValueError('Dataset identities already registered; use the existing selection')
    text = text.replace('\n})\n', '\n    # Fixed review draws, 2026-10-05\n' + '\n'.join(registrations) + '\n\n})\n', 1)
    registry.write_text(text, encoding='utf-8')
    manifest = {'selection': 'Fixed-seed proportional group sampling; distinct document IDs; excludes earlier 4x50 benchmark',
                'requested_profile': 'LOCAL_ONLY', 'sample_size': 5 * sample_size, 'corpora': corpora,
                'excluded_manifests': [str(path.resolve()) for path in exclude_manifests],
                'ground_truth_qualification': 'Agent labels are comparison evidence, not independently adjudicated accuracy'}
    truth = ground_truth or benchmark.GT
    if truth.is_file():
        frozen = output / 'agent_truth_snapshot.json'
        frozen.write_bytes(truth.read_bytes())
        manifest.update(ground_truth_snapshot=str(frozen), ground_truth_snapshot_sha256=benchmark.sha(frozen))
    benchmark.write_json(output / 'benchmark_manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run', 'summarize'))
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--profile', choices=('LOCAL_ONLY', 'PRODUCT'), default='LOCAL_ONLY')
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--sample-size', type=int, default=10)
    parser.add_argument('--exclude-manifest', type=Path, action='append', default=[])
    parser.add_argument('--ground-truth', type=Path)
    args = parser.parse_args()
    output = args.output_root.resolve()
    if args.action == 'prepare':
        prepare(output, seed=args.seed, exclude_manifests=args.exclude_manifest,
                ground_truth=args.ground_truth, sample_size=args.sample_size)
        return 0
    benchmark.OUT = output
    manifest = json.loads((output / 'benchmark_manifest.json').read_text(encoding='utf-8'))
    if args.action == 'run':
        for entry in manifest['corpora']:
            code = benchmark.run_one(entry, workers=args.workers, profile=args.profile)
            summarize(manifest, args.profile)
            if code:
                return code
    else:
        summarize(manifest, args.profile)
    return 0


def summarize(manifest, profile):
    with redirect_stdout(StringIO()):
        report = benchmark.summarize(manifest, profile)
    report['rates_denominator'] = f"All {sum(e['sample_size'] for e in manifest['corpora'])} selected documents. Non-claim classifications are unverified OCR signatures, not adjudicated page roles."
    benchmark.write_json(benchmark.OUT / f'comparison_{profile.lower()}.json', report)
    print(json.dumps({'profile': profile, 'status': report['status'], 'overall': report['overall']}), flush=True)
    return report


if __name__ == '__main__':
    raise SystemExit(main())
