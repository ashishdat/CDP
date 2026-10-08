"""Matched local critical-field reacquisition; original benchmark artifacts stay immutable."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import redirect_stdout
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--per-pool', type=int)
    parser.add_argument('--source-profile', choices=('LOCAL_ONLY', 'PRODUCT'), default='LOCAL_ONLY')
    parser.add_argument('--acquisition-profile', choices=('LOCAL_ONLY', 'PRODUCT'), default='LOCAL_ONLY')
    parser.add_argument('--document', action='append')
    parser.add_argument('--field', action='append')
    parser.add_argument('--disable-trocr', action='store_true')
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output_root.resolve()
    if output.exists():
        raise ValueError('A fresh output directory is required')
    output.mkdir(parents=True)
    from scripts import benchmark_hackathon_four_corpora as benchmark

    manifest = json.loads((source / 'benchmark_manifest.json').read_text())
    benchmark.OUT = output
    env = benchmark.run_env(output, manifest['corpora'][0]['sample_archive'], args.acquisition_profile)
    os.environ.clear()
    os.environ.update(env)
    from scripts.run_hackathon_1000_cascade import _stage_env

    # Match the benchmark's actual OCR-stage scope, reader order and flags.
    # run_env alone configures the profile but omits these stage defaults.
    env = _stage_env()
    if args.disable_trocr:
        env['CDP_TROCR_DOB_RESIDUAL'] = '0'
    os.environ.clear()
    os.environ.update(env)
    import scripts.benchmark_runtime.sitecustomize  # noqa: F401
    import torch  # Windows native libraries require Torch before Paddle.
    import cv2
    import numpy as np
    from PIL import Image
    from packages.extraction_recovery.doc_latency_budget import begin_doc_budget, reset_doc_budget
    from packages.ocr_router import OCRRouter
    from scripts.assemble_extraction_result import assemble
    from scripts.complete_from_extraction import run as complete
    from scripts.ocr_from_geometry import _load_cms1500_template, recognize_regions
    from scripts.rank_from_ocr import rank_saved
    from scripts.run_hackathon_1000_cascade import _summarize_final
    from scripts.validate_from_ranked import run as validate
    from workers.ocr_engine_factories import wire_package_ocr_providers

    torch.set_num_threads(1)
    wire_package_ocr_providers()
    router = OCRRouter(lambda attempt: True)
    critical = set(args.field or ('patient_name', 'insured_name', 'patient_dob', 'insured_id_number', 'total_charge'))
    records = []
    def save():
        report = {
            'scope': 'Matched registered images; fresh selected-field OCR; cached service lines and other fields; not fresh end-to-end registration',
            'source_root': str(source), 'selected': sum(e['sample_size'] for e in manifest['corpora']),
            'verified': len(records), 'before_stp': sum(r['before_stp'] for r in records),
            'after_stp': sum(r['after_stp'] for r in records),
            'cloud_calls': 0 if args.acquisition_profile == 'LOCAL_ONLY' else None,
            'source_profile': args.source_profile, 'acquisition_profile': args.acquisition_profile,
            'reacquired_fields': sorted(critical),
            'cloud_call_meters': [str(output / 'azure_di_meter.jsonl'), str(output / 'vlm_token_meter.jsonl')],
            'independent_accuracy_established': False, 'records': records,
            'acquisition_settings': {k: os.environ.get(k) for k in
                ('CDP_OCR_FIELD_SCOPE', 'CDP_OCR_PRIMARY_OVERRIDE', 'CDP_OCR_SELECTIVE_CONFIRM')},
        }
        benchmark.write_json(output / 'verification_summary.json', report)
    for entry in manifest['corpora']:
        run = source / args.source_profile.lower() / f"corpus_{entry['pool_size']}"
        if not (run / 'results.jsonl').exists():
            continue
        previous = {r['document']: r for r in map(json.loads, (run / 'results.jsonl').read_text().splitlines())}
        documents = entry['documents']
        if args.document:
            documents = [d for d in documents if d in args.document]
        if args.per_pool is not None:
            eligible = [d for d in documents if previous[d].get('completed')]
            accepted = [d for d in eligible if previous[d].get('true_stp')]
            blocked = sorted((d for d in eligible if not previous[d].get('true_stp')),
                             key=lambda d: (len(previous[d].get('critical_blockers') or []), d))
            preferred = accepted[:1] + blocked[:1]
            documents = (preferred + [d for d in eligible if d not in preferred])[:args.per_pool]
        with ZipFile(entry['sample_archive']) as archive:
            for document in documents:
                if args.limit is not None and len(records) >= args.limit:
                    save()
                    return
                before = previous[document]
                if not before.get('completed'):
                    continue
                cid = before['claim_id']
                old, target = run / 'claims' / cid, output / 'claims' / cid
                target.mkdir(parents=True)
                gp = next(old.rglob('GeometryResult.json'))
                geometry = json.loads(gp.read_text())
                telemetry = json.loads((gp.parent / 'geometry_telemetry.json').read_text())
                template = _load_cms1500_template(geometry, telemetry, gp.parent)
                payload = archive.read(document)
                if hashlib.sha256(payload).hexdigest() != telemetry['document_id']:
                    raise ValueError('Source image hash mismatch')
                old_ocr = old / 'ocr/OCRCandidates.json'
                old_digest = benchmark.sha(old_ocr)
                report = json.loads(old_ocr.read_text())
                with Image.open(BytesIO(payload)) as image:
                    image.seek(geometry['page_number'] - 1)
                    pixels = cv2.warpPerspective(np.asarray(image.convert('L')),
                        np.asarray(geometry['source_to_geometry_transform']),
                        (template.reference_dimensions.width_px, template.reference_dimensions.height_px), borderValue=255)
                focused = {**geometry, 'fields': [f for f in geometry['fields'] if f['field'] in critical]}
                begin_doc_budget()
                with Image.fromarray(pixels) as image, (target / 'verification.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                    acquired = recognize_regions(image, focused, router, lambda rows: None, template)
                    if args.acquisition_profile == 'PRODUCT':
                        from scripts.ocr_from_geometry import _maybe_attach_dob_handwriting_residuals

                        acquired = _maybe_attach_dob_handwriting_residuals(
                            acquired, image, service_lines=report.get('service_lines'))
                    new_fields = {f['field']: f for f in acquired}
                    report['fields'] = [new_fields.get(f['field'], f) for f in report['fields']]
                    op = target / 'ocr/OCRCandidates.json'
                    op.parent.mkdir()
                    op.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
                    st = json.loads((old / 'ocr/ocr_telemetry.json').read_text())
                    st['matched_critical_reacquisition'] = {'source_ocr_sha256': old_digest, 'fields': sorted(critical),
                        'cloud_calls': 0 if args.acquisition_profile == 'LOCAL_ONLY' else None}
                    (op.parent / 'ocr_telemetry.json').write_text(json.dumps(st, indent=2) + '\n')
                    rank_saved(op, target / 'rank')
                    validate(target / 'rank/RankedCandidates.json', target / 'validate', template.template_id, template.version)
                    assemble(op, target / 'rank/RankedCandidates.json', target / 'validate/ValidationResults.json', target / 'extract')
                    complete(target / 'extract/ExtractionResult.json', target / 'final', 'CMS1500')
                reset_doc_budget()
                after = _summarize_final(target)
                if benchmark.sha(old_ocr) != old_digest:
                    raise ValueError('Original artifact changed')
                record = {'claim_id': cid, 'pool_size': entry['pool_size'],
                          'before_stp': before['true_stp'], 'after_stp': after['true_stp'],
                          'before_fields': before['fields'], 'after_fields': after['fields'],
                          'remaining_blockers': after['critical_blockers']}
                records.append(record)
                save()
                print(json.dumps({k: record[k] for k in ('claim_id', 'before_stp', 'after_stp', 'remaining_blockers')}), flush=True)
    save()


if __name__ == '__main__':
    main()
