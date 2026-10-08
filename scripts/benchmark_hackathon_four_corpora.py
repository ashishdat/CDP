"""Reproducible stratified 50-per-corpus live hackathon benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
OUT = ROOT / 'evaluation_results' / 'benchmark_4x50_20261004'
ORIGINAL_SAMPLE = WORKSPACE / 'runs/hackathon-1000-v3.1-20260918/sample'
DOWNLOADS = Path.home() / 'Downloads'
GT = WORKSPACE / '.worktrees/cdp-v3-integrated-20261002/evaluation_data/hackathon_agent_gt/field_truth.json'
SEED = 20261004
sys.path.insert(0, str(ROOT))


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    import time
    for attempt in range(30):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(0.1)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def stratified(pool, seed, excluded=()):
    groups = defaultdict(list)
    for doc in sorted(set(pool) - set(excluded)):
        groups[doc.split('/')[0]].append(doc)
    total = sum(map(len, groups.values()))
    if total < 50:
        raise ValueError('Pool has fewer than 50 distinct available samples')
    ideal = {group: 50 * len(docs) / total for group, docs in groups.items()}
    allocation = {group: int(n) for group, n in ideal.items()}
    for group in sorted(groups, key=lambda g: (-(ideal[g] - allocation[g]), g))[:50 - sum(allocation.values())]:
        allocation[group] += 1
    rng = random.Random(seed)
    selected = sorted(doc for group in sorted(groups) for doc in rng.sample(groups[group], allocation[group]))
    assert len(selected) == len(set(selected)) == 50
    return selected, allocation


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    archive1000 = OUT / 'source/Hackathon - 1000 Claims-reconstructed.zip'
    original_manifest = ORIGINAL_SAMPLE / 'manifest.json'
    cases = json.loads(original_manifest.read_text(encoding='utf-8'))['cases']
    if len(cases) != 1000 or len({row['document'] for row in cases}) != 1000:
        raise ValueError('Original 1000-case manifest is incomplete or duplicated')
    if not archive1000.exists():
        archive1000.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive1000.with_suffix('.partial')
        with ZipFile(temporary, 'w', compression=ZIP_STORED) as archive:
            for row in cases:
                original = (ORIGINAL_SAMPLE / row['original']).resolve()
                if ORIGINAL_SAMPLE.resolve() not in original.parents:
                    raise ValueError('Original path outside sample root')
                if sha(original) != row['source_sha256']:
                    raise ValueError('Original TIFF source hash does not match manifest')
                archive.write(original, arcname=row['document'])
        temporary.replace(archive1000)
    list300 = ROOT / 'docs/metrics/similar_sample_300_v1/selected_documents.txt'
    list1000 = ROOT / 'docs/metrics/similar_sample_1000_v1/selected_documents.txt'
    pools = {300: list300.read_text().splitlines(), 1000: list1000.read_text().splitlines()}
    archives = {300: archive1000, 1000: archive1000,
                5000: DOWNLOADS / 'Hackathon - 5000 Claims.zip',
                10000: DOWNLOADS / 'Hackathon - 10000 Claims.zip'}
    seen_docs = set()
    corpora = []
    hashes = {}
    registrations = []
    for size in [300, 1000, 5000, 10000]:
        archive = archives[size]
        with ZipFile(archive) as zipped:
            names = sorted(n for n in zipped.namelist() if not n.endswith('/') and n.split('/')[0] in {'Group A','Group B','Group C','Group D'})
            pool = pools.get(size, names)
            if len(pool) != len(set(pool)) or len(pool) != size or not set(pool) <= set(names):
                raise ValueError(f'Corpus {size} membership mismatch')
            # Keep document identities disjoint across the four draws where possible.
            selected, allocation = stratified(pool, SEED + size, seen_docs)
            source_hashes = {doc: hashlib.sha256(zipped.read(doc)).hexdigest() for doc in selected}
        seen_docs.update(selected)
        run = OUT / f'corpus_{size}'
        run.mkdir(parents=True, exist_ok=True)
        (run / 'selected_documents.txt').write_text('\n'.join(selected) + '\n', encoding='utf-8')
        dataset = run / 'dataset.yaml'
        import yaml
        sample_archive = run / 'sample_50.zip'
        pages = 0
        with ZipFile(archive) as source, ZipFile(sample_archive, 'w', compression=ZIP_STORED) as packed:
            for doc in selected:
                payload = source.read(doc)
                with Image.open(BytesIO(payload)) as image:
                    pages += image.n_frames
                info = ZipInfo(doc, date_time=(2026,10,4,0,0,0))
                info.compress_type = ZIP_STORED
                packed.writestr(info, payload)
        dataset_id = f'HACKATHON_SAMPLE_{size}_50_V1'
        description = f'50-document stratified development sample from Hackathon {size}-document pool; seed {SEED}; not an independent holdout.'
        packed_hash = sha(sample_archive)
        dataset.write_text(yaml.safe_dump({'dataset_id':dataset_id, 'root':str(sample_archive.resolve()),
            'pages':pages, 'documents':50, 'description':description}), encoding='utf-8')
        registrations.append(f'''    "{dataset_id}": DatasetMetadata(
        dataset_id="{dataset_id}", version=1, type=DatasetType.VALIDATION,
        pages={pages}, documents=50, hash="{packed_hash}",
        description={description!r}, source="benchmark_4x50_20261004/corpus_{size}/sample_50.zip",
    ),''')
        hashes.setdefault(str(archive), sha(archive))
        entry = {'pool_size':size, 'sample_size':50, 'seed':SEED + size, 'allocation':allocation,
                 'archive':str(archive.resolve()), 'archive_sha256':hashes[str(archive)],
                 'dataset':str(dataset.resolve()), 'dataset_id':dataset_id, 'sample_archive':str(sample_archive.resolve()),
                 'sample_archive_sha256':packed_hash, 'sample_pages':pages, 'run_dir':str(run.resolve()),
                 'documents':selected, 'source_sha256':source_hashes}
        if size in {300,1000}:
            entry['source_reconstruction'] = {'original_manifest':str(original_manifest.resolve()),
                                              'manifest_sha256':sha(original_manifest),
                                              'original_tiff_hashes_verified':1000,
                                              'qualification':'Original source bytes preserved; archive packaging differs from original ZIP'}
        write_json(run / 'selection_manifest.json', entry)
        corpora.append(entry)
        print(f'Prepared corpus={size} sample=50 groups={allocation}', flush=True)
    registry = ROOT / 'datasets/registry.py'
    text = registry.read_text(encoding='utf-8')
    start_marker = '    # BEGIN benchmark_4x50_20261004 sample registrations\n'
    end_marker = '    # END benchmark_4x50_20261004 sample registrations\n'
    if start_marker in text:
        start = text.index(start_marker)
        end = text.index(end_marker, start) + len(end_marker)
        text = text[:start] + text[end:]
    marker = '\n})\n'
    block = '\n' + start_marker + '\n'.join(registrations) + '\n' + end_marker
    if marker not in text:
        raise ValueError('Dataset registry insertion marker unavailable')
    registry.write_text(text.replace(marker, block + marker, 1), encoding='utf-8')
    manifest = {'created_at':datetime.now(UTC).isoformat(), 'worktree':str(ROOT),
                'requested_profile':'PRODUCT', 'cloud_approval':'PENDING_EXPLICIT_AUTHORIZATION', 'selection':'stratified fixed-seed; document identities disjoint across draws',
                'critical_fields':['patient_dob','total_charge','patient_name','insured_id_number','insured_name'],
                'ground_truth':str(GT), 'ground_truth_qualification':'Agent-created OCR consensus/visual labels; NOT independent adjudicated accuracy',
                'corpora':corpora}
    write_json(OUT / 'benchmark_manifest.json', manifest)
    return manifest


def run_env(run, archive, profile):
    from dotenv import dotenv_values

    from packages.run_profiles import apply_profile_env
    env = dict(os.environ)
    filenames = ['.env', '.env.hackathon100'] if profile == 'PRODUCT' else ['.env']
    for filename in filenames:
        for key, value in dotenv_values(ROOT / filename).items():
            if value is not None:
                env[key] = value
    env, _profile = apply_profile_env('PRODUCT' if profile == 'PRODUCT' else 'FAST', env)
    if profile == 'LOCAL_ONLY':
        # No external services or credentials: local-only is not PRODUCT parity.
        for key in list(env):
            if any(provider in key.upper() for provider in ['AZURE', 'ANTHROPIC', 'OPENAI']):
                env.pop(key)
        env.update({
            'CDP_CONTEXT_DOB_RECOVERY':'0', 'CDP_GPT4O_CROP_RESIDUAL':'0', 'CDP_GPT4O_CROP_ACCEPT':'0',
            'CDP_GPT4O_EMPTY_FINANCE':'0', 'CDP_CONFLICT_AGENT':'0',
            'CDP_AZURE_DI_CHARGE_RESIDUAL':'0', 'CDP_AZURE_DI_CHARGE_CORROBORATE':'0',
            'CDP_AZURE_DI_CHARGE_ACCEPT':'0', 'CDP_AZURE_DI_DOB_RESIDUAL':'0',
            'CDP_AZURE_DI_PAGE_CORNERS':'0', 'CDP_UNSTRUCTURED_REG_FALLBACK':'0',
            'CDP_UNSTRUCTURED_REG_AGENT':'0', 'CDP_TROCR_DOB_RESIDUAL':'0',
            'CDP_LEARNED_MATCHER':'0', 'CDP_OCR_LOCK':'0', 'HF_HUB_OFFLINE':'1', 'TRANSFORMERS_OFFLINE':'1',
        })
    # Both CLI adapters and direct pytesseract calls need the Windows executable.
    tesseract = Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe')
    if os.name == 'nt' and tesseract.is_file():
        env['TESSERACT_CMD'] = str(tesseract)
        env['PATH'] = str(tesseract.parent) + os.pathsep + env.get('PATH', '')
    # Only this benchmark and its descendants load the thread-cap hook.
    runtime_dir = str(ROOT / 'scripts/benchmark_runtime')
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [runtime_dir, env.get('PYTHONPATH')]))
    env['CDP_BENCHMARK_ONNX_THREADS'] = '1'
    # Preserve the PRODUCT flags while replacing POSIX-only scratch locations.
    env.update({'CDP_CASCADE_RESPECT_ENV':'1', 'PYTHONIOENCODING':'utf-8',
                'OMP_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
                'CDP_HACKATHON_ZIP':str(archive), 'CDP_PIPELINE_RELEASE':'extraction-v3',
                'CDP_AZURE_DI_METER_PATH':str(run / 'azure_di_meter.jsonl'),
                'CDP_VLM_TOKEN_METER_PATH':str(run / 'vlm_token_meter.jsonl'),
                'CDP_OCR_LOCK_PATH':str(OUT / 'locks/ocr.lock'),
                'CDP_AZURE_DI_SLOT_PATH':str(OUT / 'locks/azure-di-slot'),
                'CDP_VLM_CROP_LOCK_PATH':str(OUT / 'locks/vlm-crop.lock')})
    (OUT / 'locks').mkdir(exist_ok=True)
    return env


def run_one(entry, smoke=False, workers=1, profile="LOCAL_ONLY"):
    run = OUT / profile.lower() / (f"corpus_{entry['pool_size']}" if not smoke else 'smoke_registered')
    run.mkdir(parents=True, exist_ok=True)
    docs = entry['documents'][:1] if smoke else entry['documents']
    env = run_env(run, entry['sample_archive'], profile)
    write_json(run / 'benchmark_runtime.json', {'profile':profile,'cloud_enabled':profile=='PRODUCT','dataset_id':entry['dataset_id'],'parent_pool_size':entry['pool_size'],'workers':workers,
        'classification_mode':'AUTO','architecture_version':'independent-failure-recovery-v2',
        'sample_size':len(docs),'fresh_inference':True,'seed':entry['seed'],'onnx_threads':1,'ocr_inference_serialized':env.get('CDP_OCR_LOCK','1')!='0','tesseract_executable':env.get('TESSERACT_CMD'),
        'operational_overrides':['Windows scratch paths','UTF-8 logs','one BLAS thread'],
        'residual_flags':{k:env[k] for k in ['CDP_GPT4O_CROP_RESIDUAL','CDP_AZURE_DI_CHARGE_RESIDUAL','CDP_TROCR_DOB_RESIDUAL','CDP_CONFLICT_AGENT']}})
    command = [sys.executable,'-u',str(ROOT / 'scripts/run_hackathon_1000_cascade.py'),
               '--zip',entry['sample_archive'],'--dataset',entry['dataset'],'--out-dir',str(run),
               '--documents',','.join(docs),'--workers',str(workers),'--resume']
    print(f"Starting {'smoke' if smoke else entry['pool_size']} docs={len(docs)} workers={workers}",flush=True)
    with (run / 'console.log').open('w',encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=False)
    write_json(run / 'execution.json',{'returncode':result.returncode,'finished_at':datetime.now(UTC).isoformat()})
    print(f"Finished {'smoke' if smoke else entry['pool_size']} exit={result.returncode}",flush=True)
    return result.returncode


def summarize(manifest, profile="LOCAL_ONLY"):
    from scripts.score_hackathon_gt_accuracy import score
    truth_path = Path(manifest.get('ground_truth_snapshot', GT))
    if manifest.get('ground_truth_snapshot_sha256') and sha(truth_path) != manifest['ground_truth_snapshot_sha256']:
        raise ValueError('Frozen agent-label snapshot hash changed')
    gt = json.loads(truth_path.read_text(encoding='utf-8')) if truth_path.is_file() else {'claims':{}}
    comparison=[]
    for entry in manifest['corpora']:
        run=OUT / profile.lower() / f"corpus_{entry['pool_size']}"; by_doc={}
        ledger=run / 'results.jsonl'
        if ledger.exists():
            for line in ledger.read_text(encoding='utf-8').splitlines(keepends=True):
                if not line.endswith('\n'):
                    continue  # A different corpus worker can still be appending.
                row=json.loads(line); by_doc[row.get('document')]=row
        rows=[by_doc[d] for d in entry['documents'] if d in by_doc and by_doc[d].get('finished')]
        completed=[r for r in rows if r.get('completed')]
        stp=sum(bool(r.get('true_stp')) for r in completed)
        hitl=sum(r.get('disposition')=='HITL' for r in completed)
        ids={d.replace('/','__') for d in entry['documents']}
        subset={'claims':{k:v for k,v in gt.get('claims',{}).items() if k in ids}}
        proxy=score(run,subset)
        write_json(run / 'agent_label_agreement.json',proxy)
        n=entry['sample_size']; done=len(completed)
        # NOT_A_CLAIM_DOCUMENT is the current ledger value for mailroom/fax
        # pages; older runs recorded the same pages as REGISTRATION_FAILED
        # with unstructured_reg_fallback.reason=='MAILROOM_OR_FAX' â€” count both.
        not_a_claim_rows=[r for r in rows if r.get('disposition')=='NOT_A_CLAIM_DOCUMENT'
            or (r.get('disposition')=='REGISTRATION_FAILED' and (r.get('unstructured_reg_fallback') or {}).get('reason')=='MAILROOM_OR_FAX')]
        true_reg_failed_rows=[r for r in rows if r.get('disposition')=='REGISTRATION_FAILED' and r not in not_a_claim_rows]
        fallback_review_rows=[r for r in completed if r.get('registration_ok') is False
            and r.get('disposition')=='HITL']
        from packages.recovery.independent_failures import failure_category
        categories = Counter(failure_category(r) for r in rows)
        from packages.evaluation.family_metrics import family_metrics
        verified_path = manifest.get('verified_truth_snapshot')
        verified = json.loads(Path(verified_path).read_text(encoding='utf-8')) if verified_path else None
        family_report = family_metrics(rows, selected_count=n, truth=verified)
        comparison.append({'corpus_size':entry['pool_size'],'sample_size':n,'finished':len(rows),'completed':done,
            'stp_count':stp,'hitl_count':hitl,'failure_count':len(rows)-done-len(not_a_claim_rows),
            'registration_failure_count':categories['ALIGNMENT_FAILURE'],
            'non_claim_document_count':len(not_a_claim_rows),
            'true_registration_failure_count':categories['ALIGNMENT_FAILURE'],
            'legacy_registration_failed_disposition_count':len(true_reg_failed_rows),
            'registration_fallback_hitl_count':len(fallback_review_rows),
            'template_selection_failure_count':categories['TEMPLATE_SELECTION_FAILURE'],
            'alignment_failure_count':categories['ALIGNMENT_FAILURE'],
            'runtime_error_count':categories['RUNTIME_ERROR'],
            'unclassified_stage_failure_count':categories['UNCLASSIFIED_STAGE_FAILURE'],
            'failure_category_counts':dict(categories),
            'family_evaluation':family_report,
            'pending':n-len(rows), 'status':'COMPLETE' if len(rows)==n else 'RUNNING',
            'stp_rate_of_all':stp/n,'hitl_rate_of_all':hitl/n,
            'stp_rate_of_completed':stp/done if done else None,'hitl_rate_of_completed':hitl/done if done else None,
            'independent_accuracy':None,'independent_accuracy_status':'INDEPENDENT_ADJUDICATED_LABELS_NOT_AVAILABLE',
            'agent_label_agreement':proxy['exact_accuracy'] if proxy['field_count'] else None,
            'agent_labeled_claims_scored':proxy['claims_scored'],'agent_labeled_fields_scored':proxy['field_count'],
            'agent_labels_claim_coverage':proxy['claims_scored']/n,'agent_label_false_accepts':proxy['false_accepts'],
            'accuracy_qualification':'Partial agent-label agreement only; not independent accuracy',
            'dispositions':dict(Counter(r.get('disposition','UNKNOWN') for r in rows))})
    result={'manifest':str(OUT / 'benchmark_manifest.json'),'profile':profile,
            'status':'COMPLETE' if all(r['pending']==0 for r in comparison) else 'RUNNING',
            'operational_qualification':'Local-only FAST-derived development benchmark; not PRODUCT release-gate evidence' if profile=='LOCAL_ONLY' else 'PRODUCT development benchmark',
            'release_gate_eligible':False,
            'ground_truth_snapshot_sha256':manifest.get('ground_truth_snapshot_sha256'),
            'overall':{key:sum(r[key] for r in comparison) for key in ['sample_size','finished','completed','stp_count','hitl_count','failure_count','registration_failure_count','non_claim_document_count','true_registration_failure_count','registration_fallback_hitl_count','template_selection_failure_count','alignment_failure_count','runtime_error_count','unclassified_stage_failure_count','legacy_registration_failed_disposition_count','pending']},
            'rates_denominator':'All 50 selected claims per corpus; registration and infrastructure failures are separate from HITL. Non-claim page signatures are reported separately and remain unverified unless adjudicated. Template selection, alignment and runtime categories are distinct; registration_failure_count means alignment failures only. Root-stage counts can include fallback HITL claims.',
            'comparison':comparison}
    from packages.evaluation.run_reporting import build as build_run_report
    corrected=build_run_report(OUT,manifest=manifest,profile=profile)
    write_json(OUT / 'reporting_status.json',corrected)
    result['terminal_outcomes']=corrected['terminal_outcomes']
    result['reporting_issue_counts']=corrected['reporting_issue_counts']
    result['stage_categories_with_completed_hitl']=corrected['stage_categories_with_completed_hitl']
    result['rates_denominator']='Selected documents from the manifest; terminal outcomes and overlapping stage categories are separate. Pending-aware rates are in terminal_outcomes.rates.'
    write_json(OUT / f'comparison_{profile.lower()}.json',result)
    import csv
    with (OUT / f'comparison_{profile.lower()}.csv').open('w',newline='',encoding='utf-8') as f:
        keys=[k for k in comparison[0] if k!='dispositions']
        writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(comparison)
    print(json.dumps(result,indent=2),flush=True)
    return result


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','smoke','run','summarize'])
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--profile',choices=['LOCAL_ONLY','PRODUCT'],default='LOCAL_ONLY')
    parser.add_argument('--corpus',type=int,choices=[300,1000,5000,10000])
    parser.add_argument('--output-root',type=Path,help='Fresh result directory; input selections remain frozen')
    args=parser.parse_args()
    if args.action=='prepare': prepare();return 0
    source_manifest = OUT / 'benchmark_manifest.json'
    manifest=json.loads(source_manifest.read_text(encoding='utf-8'))
    if args.output_root is not None:
        OUT = args.output_root.resolve()
        OUT.mkdir(parents=True,exist_ok=True)
        manifest = {**manifest, 'selection_manifest_reference':str(source_manifest),
                    'rerun_classification':'AUTO','rerun_architecture':'independent-failure-recovery-v2'}
        write_json(OUT / 'benchmark_manifest.json',manifest)
    if args.action=='summarize':summarize(manifest,args.profile);return 0
    if args.action=='smoke':return run_one(manifest['corpora'][0],smoke=True,workers=args.workers,profile=args.profile)
    codes=[]
    for entry in manifest['corpora']:
        if args.corpus is None or entry['pool_size']==args.corpus:
            codes.append(run_one(entry,workers=args.workers,profile=args.profile));summarize(manifest,args.profile)
    return max(codes,default=0)


if __name__=='__main__':
    raise SystemExit(main())
